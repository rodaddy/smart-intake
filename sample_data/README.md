# Sample Data

Realistic sample data for demonstrating Smart Intake.

## Files

### `intake_form.txt`

A filled-out client intake questionnaire (text format). Represents a prospective client submitting information about a personal injury (slip and fall) case.

### `existing_clients.csv`

A firm's existing client list for conflict checking.

| Column | Description |
|--------|-------------|
| `client_name` | Client's full name or business name |
| `matter` | Brief description of the legal matter |
| `opposing_party` | The opposing party in the matter (if any) |
| `status` | Matter status: Active, Closed, or Pending |

The sample data includes 15 clients across multiple practice areas. Note: it intentionally contains a conflict scenario -- the prospective client's opposing party (ShopRite) is an existing client of the firm.

### `fee_schedule.csv`

The firm's fee schedule by matter type.

| Column | Description |
|--------|-------------|
| `matter_type` | Legal matter category |
| `fee_structure` | Billing model: Hourly, Flat Fee, Contingency, Retainer, or Hybrid |
| `hourly_rate` | Rate per hour (if applicable) |
| `estimated_hours` | Typical hours for this matter type |
| `range_low` | Low end of typical fee range |
| `range_high` | High end of typical fee range |
| `retainer_amount` | Required retainer (if applicable) |
| `contingency_percentage` | Contingency fee percentage (if applicable) |
