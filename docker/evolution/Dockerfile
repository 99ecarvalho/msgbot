FROM atendai/evolution-api:v2.2.3

# Apply LID patches for Baileys 6.7.12
COPY apply-patches.js /tmp/apply-patches.js
RUN node /tmp/apply-patches.js && rm /tmp/apply-patches.js
