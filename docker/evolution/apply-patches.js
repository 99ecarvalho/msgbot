/*
 * Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
 *
 * This file is part of MsgBot. It is free software, licensed under the GNU
 * Lesser General Public License v3.0 or later. See COPYING.LESSER and
 * COPYING for details.
 *
 * SPDX-License-Identifier: LGPL-3.0-or-later
 */

/**
 * Patches for Evolution API v2.2.3 / Baileys 6.7.12
 *
 * Fixes LID (Linked Identity) handling that broke after WhatsApp's LID migration.
 * Without these patches:
 *   - DMs to @lid contacts fail validation (onWhatsApp returns exists:false)
 *   - Group messages fail with "SessionError: No sessions" because participant
 *     JIDs are incorrectly encoded as @s.whatsapp.net instead of @lid
 *
 * The same fixes, as source commits, are pinned as submodules in external/
 * (not fetched by default; see doc/evolution/README.md):
 *   Patch 1: evolution-api fix/lid-validation-bypass, commit 145209b
 *   Patches 2-3: Baileys fix/lid-jid-encoding, commit cfcc772
 *
 * Run: node apply-patches.js
 */
const fs = require('fs');
const path = require('path');

let patchCount = 0;

function patchFile(filePath, replacements) {
  if (!fs.existsSync(filePath)) {
    console.error(`SKIP: ${filePath} not found`);
    return;
  }

  let content = fs.readFileSync(filePath, 'utf8');
  let changed = false;

  for (const [desc, search, replace] of replacements) {
    if (content.includes(replace)) {
      console.log(`  ALREADY APPLIED: ${desc}`);
      continue;
    }
    if (!content.includes(search)) {
      console.error(`  NOT FOUND: ${desc}`);
      console.error(`    Search string: ${JSON.stringify(search).slice(0, 120)}`);
      continue;
    }
    content = content.replace(search, replace);
    changed = true;
    patchCount++;
    console.log(`  PATCHED: ${desc}`);
  }

  if (changed) {
    fs.writeFileSync(filePath, content);
  }
}

// ---------------------------------------------------------------------------
// Patch 1: main.js — Allow @lid contacts to bypass onWhatsApp validation
// ---------------------------------------------------------------------------
console.log('\n[1/3] Patching dist/main.js — LID validation bypass');
patchFile('/evolution/dist/main.js', [
  [
    'Whitelist @lid in sendMessageWithTyping validation',
    '!n.jid.includes("@broadcast"))throw new f(n)',
    '!n.jid.includes("@broadcast")&&!n.jid.includes("@lid"))throw new f(n)',
  ],
]);

// ---------------------------------------------------------------------------
// Patch 2: signal.js — Preserve participant server/domain in extractDeviceJids
// ---------------------------------------------------------------------------
console.log('\n[2/3] Patching baileys/Utils/signal.js — preserve JID server in extractDeviceJids');
patchFile('/evolution/node_modules/baileys/lib/Utils/signal.js', [
  [
    'Extract server from jidDecode',
    'const { user } = (0, WABinary_1.jidDecode)(id);',
    'const { user, server } = (0, WABinary_1.jidDecode)(id);',
  ],
  [
    'Include server in returned device objects',
    'extracted.push({ user, device });',
    'extracted.push({ user, device, server });',
  ],
]);

// ---------------------------------------------------------------------------
// Patch 3: messages-send.js — Use actual participant domain for group messages
// ---------------------------------------------------------------------------
console.log('\n[3/3] Patching baileys/Socket/messages-send.js — per-participant JID domain');
patchFile('/evolution/node_modules/baileys/lib/Socket/messages-send.js', [
  [
    'patchMessageBeforeSending: use d.server for participant JID encoding',
    "devices.map(d => (0, WABinary_1.jidEncode)(d.user, isLid ? 'lid' : 's.whatsapp.net', d.device))",
    "devices.map(d => (0, WABinary_1.jidEncode)(d.user, d.server || (isLid ? 'lid' : 's.whatsapp.net'), d.device))",
  ],
  [
    'SenderKey loop: destructure server from device',
    "for (const { user, device } of devices) {\n                    const jid = (0, WABinary_1.jidEncode)(user, isLid ? 'lid' : 's.whatsapp.net', device);",
    "for (const { user, device, server: dServer } of devices) {\n                    const jid = (0, WABinary_1.jidEncode)(user, dServer || (isLid ? 'lid' : 's.whatsapp.net'), device);",
  ],
]);

// ---------------------------------------------------------------------------
console.log(`\nDone — ${patchCount} patch(es) applied.\n`);
