CREATE OR REPLACE FUNCTION cra_control.claim_next_job(
  p_worker_id text,
  p_worker_version text,
  p_capabilities jsonb,
  p_queue_names text[]
) RETURNS TABLE(
  job_id text, workspace_id text, project_id text, attempt_id text,
  execution_token text, queue_name text, resource_class text,
  task_schema_version integer, request_hash text
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cra_control
AS $$
DECLARE
  candidate record;
  raw_token text;
BEGIN
  SELECT j.job_id, j.workspace_id, j.project_id, a.attempt_id, j.queue_name,
         j.resource_class, j.task_schema_version, j.request_hash
  INTO candidate
  FROM cra_control.jobs j
  JOIN cra_control.job_attempts a
    ON a.job_id=j.job_id AND a.attempt_number=j.current_attempt_number
  WHERE j.status='dispatched' AND j.queue_name=ANY(p_queue_names)
    AND a.status='dispatched'
    AND (NOT (p_capabilities ? 'job_id') OR j.job_id=p_capabilities->>'job_id')
    AND (NOT (p_capabilities ? 'attempt_id') OR a.attempt_id=p_capabilities->>'attempt_id')
    AND EXISTS (
      SELECT 1 FROM cra_control.worker_registry w
      WHERE w.worker_id_hash=encode(digest(p_worker_id,'sha256'),'hex')
        AND j.task_schema_version BETWEEN w.min_task_schema_version AND w.max_task_schema_version
    )
  ORDER BY j.priority DESC, j.created_at
  FOR UPDATE OF j,a SKIP LOCKED LIMIT 1;
  IF candidate IS NULL THEN RETURN; END IF;
  raw_token := encode(gen_random_bytes(32),'hex');
  UPDATE cra_control.jobs SET status='running', worker_id_hash=encode(digest(p_worker_id,'sha256'),'hex'),
    execution_token_hash=encode(digest(raw_token,'sha256'),'hex'), updated_at=clock_timestamp()
    WHERE cra_control.jobs.job_id=candidate.job_id;
  UPDATE cra_control.job_attempts SET status='claimed', worker_id_hash=encode(digest(p_worker_id,'sha256'),'hex'),
    execution_token_hash=encode(digest(raw_token,'sha256'),'hex')
    WHERE cra_control.job_attempts.attempt_id=candidate.attempt_id;
  RETURN QUERY SELECT candidate.job_id, candidate.workspace_id, candidate.project_id,
    candidate.attempt_id, raw_token, candidate.queue_name, candidate.resource_class,
    candidate.task_schema_version, candidate.request_hash;
END $$;

CREATE OR REPLACE FUNCTION cra_control.claim_outbox_batch(
  p_dispatcher_id text, p_min_schema integer, p_max_schema integer, p_batch_size integer
) RETURNS TABLE(
  outbox_event_id text, job_id text, attempt_id text, task_schema_version integer,
  message_deduplication_key text, claim_token text, payload jsonb
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cra_control
AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    SELECT o.outbox_event_id
    FROM cra_control.outbox_events o
    WHERE (o.status='pending' OR (o.status='publishing' AND o.lease_until<clock_timestamp()))
      AND (o.next_retry_at IS NULL OR o.next_retry_at<=clock_timestamp())
      AND o.task_schema_version BETWEEN p_min_schema AND p_max_schema
      AND EXISTS (
        SELECT 1 FROM cra_control.worker_registry w
        WHERE o.task_schema_version BETWEEN w.min_task_schema_version AND w.max_task_schema_version
          AND w.queue_names ? ('cra.' || COALESCE(o.payload->>'job_type','maintenance'))
          AND w.heartbeat_at > clock_timestamp()-interval '90 seconds'
      )
    ORDER BY o.updated_at FOR UPDATE SKIP LOCKED LIMIT p_batch_size
  ), tokens AS (
    SELECT c.outbox_event_id, encode(gen_random_bytes(32),'hex') AS raw_token FROM candidates c
  ), updated AS (
    UPDATE cra_control.outbox_events o SET status='publishing',
      claim_token_hash=encode(digest(t.raw_token,'sha256'),'hex'),
      lease_owner_hash=encode(digest(p_dispatcher_id,'sha256'),'hex'),
      lease_until=clock_timestamp()+interval '30 seconds', publish_attempt=o.publish_attempt+1,
      updated_at=clock_timestamp()
    FROM tokens t WHERE o.outbox_event_id=t.outbox_event_id
    RETURNING o.*, t.raw_token
  )
  SELECT u.outbox_event_id,u.job_id,u.attempt_id,u.task_schema_version,
         u.message_deduplication_key,u.raw_token,u.payload FROM updated u;
END $$;

CREATE OR REPLACE FUNCTION cra_control.acknowledge_outbox_publish(
  p_outbox_event_id text, p_claim_token text, p_message_id text
) RETURNS boolean
LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, cra_control
AS $$
  WITH published AS (
    UPDATE cra_control.outbox_events SET status='published', claim_token_hash=NULL,
      lease_owner_hash=NULL, lease_until=NULL, published_message_id=p_message_id,
      updated_at=clock_timestamp()
    WHERE outbox_event_id=p_outbox_event_id AND status='publishing'
      AND claim_token_hash=encode(digest(p_claim_token,'sha256'),'hex')
    RETURNING job_id,attempt_id
  ), updated_job AS (
    UPDATE cra_control.jobs j SET status='dispatched',updated_at=clock_timestamp()
    FROM published p WHERE j.job_id=p.job_id AND j.status IN ('queued','dispatching')
    RETURNING j.job_id
  )
  UPDATE cra_control.job_attempts a SET status='dispatched'
  FROM published p WHERE a.attempt_id=p.attempt_id AND a.status='created'
  RETURNING true
$$;

CREATE OR REPLACE FUNCTION cra_control.claim_periodic_window(
  p_schedule_name text, p_scheduled_window timestamptz,
  p_job_type text, p_workspace_scope text
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cra_control
AS $$
BEGIN
  INSERT INTO cra_control.periodic_windows(schedule_name,scheduled_window,job_type,workspace_scope)
  VALUES(p_schedule_name,p_scheduled_window,p_job_type,p_workspace_scope)
  ON CONFLICT DO NOTHING;
  RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION cra_control.claim_next_job(text,text,jsonb,text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION cra_control.claim_outbox_batch(text,integer,integer,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION cra_control.acknowledge_outbox_publish(text,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION cra_control.claim_periodic_window(text,timestamptz,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cra_control.claim_next_job(text,text,jsonb,text[]) TO cra_worker;
GRANT EXECUTE ON FUNCTION cra_control.claim_outbox_batch(text,integer,integer,integer) TO cra_scheduler;
GRANT EXECUTE ON FUNCTION cra_control.acknowledge_outbox_publish(text,text,text) TO cra_scheduler;
GRANT EXECUTE ON FUNCTION cra_control.claim_periodic_window(text,timestamptz,text,text) TO cra_scheduler;
