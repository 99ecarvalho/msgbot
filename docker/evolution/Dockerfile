# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

FROM atendai/evolution-api:v2.2.3

# Apply LID patches for Baileys 6.7.12
COPY apply-patches.js /tmp/apply-patches.js
RUN node /tmp/apply-patches.js && rm /tmp/apply-patches.js
