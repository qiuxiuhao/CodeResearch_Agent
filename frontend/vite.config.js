/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            "/analysis": "http://127.0.0.1:8000",
            "/library": "http://127.0.0.1:8000",
            "/llm": "http://127.0.0.1:8000",
            "/vision": "http://127.0.0.1:8000",
            "/image-generation": "http://127.0.0.1:8000",
            "/settings": "http://127.0.0.1:8000",
            "/health": "http://127.0.0.1:8000"
        }
    },
    test: {
        environment: "jsdom",
        setupFiles: "./src/setupTests.ts",
        globals: true
    }
});
