# AIVA for Home Assistant

Custom Home Assistant integration to connect a real AIVA backend with Home Assistant conversation and home sync workflows.

## Installation with HACS

1. Use `https://github.com/home-assistant-aiva/assistant-aiva` as the repository URL.
2. In Home Assistant, open `HACS`.
3. Go to `Integrations`.
4. Open `Custom repositories`.
5. Paste `https://github.com/home-assistant-aiva/assistant-aiva`.
6. Select `Integration` as the category.
7. Install `AIVA`.
8. Restart Home Assistant.
9. Go to `Settings > Devices & Services > Add Integration`.
10. Search for `AIVA` and complete the setup flow.

## Manual installation

1. Copy `custom_components/aiva` into `config/custom_components/aiva`.
2. Restart Home Assistant.
3. Add the `AIVA` integration from the UI.

## Pairing code setup

During setup, Home Assistant will ask for:

- `AIVA backend URL`
- `Home name`
- `AIVA plan`

After the initial request, Home Assistant shows a linking code and a direct link to the Telegram bot `@aiva_asistente_1_bot`.

1. Open the bot from the link shown in Home Assistant, or search for `@aiva_asistente_1_bot` in Telegram.
2. Send the exact linking code to the bot.
3. Return to Home Assistant and continue the activation flow.

If activation succeeds, the integration stores the backend URL, home metadata, `home_id`, secret, and plan. The polling interval can be adjusted later in the integration options.

## Updates

- HACS: update the integration from `HACS > Integrations` and restart Home Assistant.
- Manual: replace `config/custom_components/aiva` with the new version and restart Home Assistant.
