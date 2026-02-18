# Colab Deployment (T4)

Use `voicebox_t4_deploy.ipynb` to run the full Voicebox backend in Google Colab, so Colab handles all Qwen3-TTS audio generation.

## What the notebook configures

- `VOICEBOX_COLAB_PROFILE=true`
- `VOICEBOX_HOST=0.0.0.0`
- `VOICEBOX_PORT=17493`
- `VOICEBOX_DEFAULT_MODEL_SIZE=0.6B`
- `VOICEBOX_API_KEY` for remote protection
- `VOICEBOX_DATA_DIR` (recommended in Google Drive)
- optional `VOICEBOX_GROQ_API_KEY` for Story Director endpoints

## Secret handling

- Do not hardcode real keys in the notebook before committing.
- The notebook supports runtime secret input (`getpass`) and Colab Secrets (`google.colab.userdata`).
- Keep `VOICEBOX_API_KEY`, `VOICEBOX_GROQ_API_KEY`, and `NGROK_AUTH_TOKEN` out of Git.

## Runtime outputs

The notebook prints:

- local URL (`http://127.0.0.1:17493`)
- public ngrok URL
- ready-to-copy API key reminder
- smoke test results for `/health`, `/runtime`, `/models/status`

## Connect from Voicebox app

1. Open `Server -> Connection`.
2. Set `Server URL` to the ngrok URL.
3. Set `API Key` to `VOICEBOX_API_KEY`.
4. Save and run a generation.

## Notes

- Colab sessions are ephemeral; keep data in Drive via `VOICEBOX_DATA_DIR`.
- ngrok URL changes after restart; update app URL after each new session.
