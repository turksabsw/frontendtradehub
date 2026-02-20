# TR Contract Center

Contract Management System with Digital/Wet Signature Support for Frappe Framework.

## Overview

TR Contract Center is a standalone Frappe application for managing contracts, terms & conditions, and signatures (both digital and wet signatures).

## Features

- **Contract Templates**: Versioned contract templates with SHA256 hash verification
- **Contract Instances**: Individual contracts instantiated from templates
- **Revision Tracking**: Complete revision history for all contracts
- **Digital Signature**: Integration with e-signature providers (Turkcell, E-Imza.gov)
- **Wet Signature**: Support for physical signatures with PDF upload
- **Workflow Management**: Draft → Sent → Pending Signature → Signed/Rejected → Expired

## DocTypes

| DocType | Description |
|---------|-------------|
| Contract Template | Versioned T&C templates with content hash |
| Contract Instance | Individual contracts derived from templates |
| Contract Revision | Revision history tracking |
| ESign Provider | E-signature provider configuration |
| ESign Transaction | Signature transaction records |

## Installation

```bash
cd frappe-bench
bench get-app tr_contract_center
bench --site [sitename] install-app tr_contract_center
bench migrate
```

## API Endpoints

```
POST /api/method/tr_contract_center.api.create_instance
POST /api/method/tr_contract_center.api.sign_wet
POST /api/method/tr_contract_center.api.init_digital_sign
POST /api/method/tr_contract_center.api.esign_callback
GET  /api/method/tr_contract_center.api.get_contracts
```

## Signature Methods

### Digital Signature
- Provider callback system
- External ID tracking
- Automatic signed PDF storage

### Wet Signature
- Generate PDF for printing
- Upload scanned/photographed signed document
- Mandatory signed_pdf validation

## License

MIT
