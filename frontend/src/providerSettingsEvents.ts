export const PROVIDER_SETTINGS_UPDATED = "provider-settings-updated";

export function notifyProviderSettingsUpdated() {
  window.dispatchEvent(new Event(PROVIDER_SETTINGS_UPDATED));
}
