# TR-TradeHub

TR-TradeHub (TurkAlibaba) is a comprehensive hybrid marketplace platform combining Alibaba-style B2B/B4B wholesale trade with eBay-style C2C individual sales features.

## Features

- **Multi-Tenant Architecture**: Each seller gets an isolated interface with their own dashboard
- **B2B RFQ/Quote System**: Request for Quotation, negotiation, and award workflows
- **Multi-Seller Cart**: Single checkout creates separate sub-orders per seller
- **Escrow Payment System**: Secure fund holding until delivery confirmation
- **Turkish E-Invoice**: E-Fatura/E-Arsiv compliant invoice generation
- **Seller Performance Scoring**: Automatic KPI calculation with tier/badge system
- **C2C Auction System**: eBay-style bidding with proxy bids

## Installation

```bash
cd frappe-bench
bench get-app tr_tradehub
bench --site your-site install-app tr_tradehub
```

## Requirements

- Frappe Framework v15+
- ERPNext v15+
- Python 3.10+
- Node.js 18+
- MariaDB 10.6.6+

## License

MIT
