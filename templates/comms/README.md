# Comms playbook templates

One template per stage (investigating, identified, monitoring, resolved) x severity (SEV1-SEV4): 16 files.
Placeholders: {{title}}, {{detail}}. Cadence: SEV1 every 30m, SEV2 every 60m, SEV3 every 4h, SEV4 daily.
The same content is available programmatically via `fde_incident_response.comms.render_status_update`.
