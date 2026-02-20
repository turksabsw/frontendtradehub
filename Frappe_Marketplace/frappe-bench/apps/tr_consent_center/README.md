# TR Consent Center

KVKK/GDPR Compliant Consent Management System for Frappe Framework.

## Overview

TR Consent Center is a standalone Frappe application designed to manage user consents in compliance with Turkish KVKK (Kisisel Verilerin Korunmasi Kanunu) and EU GDPR regulations.

## Features

- **Multi-Channel Consent Tracking**: Website, Call Center, Mobile App, etc.
- **Consent Topics**: Campaigns, Notifications, Offers (dynamically configurable)
- **Multiple Communication Methods**: Phone, Email, SMS, WhatsApp, Push notifications
- **Versioned Consent Texts**: SHA256 hash verification with automatic version increment
- **Dynamic Party Linking**: Links to any DocType via Dynamic Link
- **Immutable Audit Logs**: Complete audit trail that cannot be deleted
- **Retention Policy Enforcement**: Prevents deletion before retention period ends
- **Scheduler Jobs**: Automated expiry checks and notifications

## DocTypes

| DocType | Description |
|---------|-------------|
| Consent Channel | Where consent was collected (Website, Call Center, Mobile App) |
| Consent Topic | What the consent is for (Campaigns, Notifications, Offers) |
| Consent Method | Communication method (phone/email/sms/whatsapp/push) |
| Consent Text | Versioned consent text with SHA256 hash |
| Consent Record | The actual consent record with party linking |
| Consent Audit Log | Immutable audit trail |

## Installation

```bash
cd frappe-bench
bench get-app tr_consent_center
bench --site [sitename] install-app tr_consent_center
bench migrate
```

## API Endpoints

```
POST /api/method/tr_consent_center.api.grant_consent
POST /api/method/tr_consent_center.api.revoke_consent
GET  /api/method/tr_consent_center.api.get_consents
GET  /api/method/tr_consent_center.api.get_current_text
```

## License

MIT
