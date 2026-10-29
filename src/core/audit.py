# OmniCast - Personal Offline Video Server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later.

from sqlalchemy.orm import Session

from models.db import AuditLog

def log_action(db: Session, user_id: int, action: str, details: str = ""):
    log = AuditLog(user_id=user_id, action=action, details=details)
    db.add(log)
    db.commit()