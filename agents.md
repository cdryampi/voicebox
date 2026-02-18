# Voicebox AI Agent Guide

This document provides context for AI agents working on the Voicebox project.

## Project Vision
Voicebox is a local-first voice synthesis studio. It prioritizes privacy, native performance (Tauri), and high-quality voice cloning (Qwen3-TTS).

## Project Structure
- `app/`: Shared React frontend (components, hooks, logic).
- `backend/`: Python FastAPI server.
  - `main.py`: Entry point for the API.
  - `models.py`: Request/Response schemas.
  - `tts.py`: Voice synthesis implementation.
- `tauri/`: Desktop application wrapper (Rust).
- `web/`: Web application wrapper.

## Running the Backend (WSL)
The backend is configured to run inside **WSL (Ubuntu-24.04)**.
- **Launch Script:** `start_voicebox_wsl.bat` (from Windows).
- **Backend Port:** 17493.
- **Virtual Environment:** `backend/.venv_wsl/`.

## Key Files
- `backend/main.py`: Main API orchestration.
- `app/src/lib/api/`: Generated API client.
- `voicebox/README.md`: General overview and features.

## Development Workflow
1. Start the backend via WSL (usually port 17493).
2. Start the frontend via Bun (usually port 5174 or 5173).
3. Ensure the frontend `baseUrl` matches the backend address.
