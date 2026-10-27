# HemoGrid ER diagram

Renders on GitHub, in VS Code (Markdown Preview Mermaid) or at mermaid.live.

```mermaid
erDiagram
    PERSON ||--o| DONOR : "is a"
    PERSON ||--o| RECIPIENT : "is a"
    PERSON ||--o| STAFF : "is a"
    DONOR ||--o{ DONOR_PHONE : has
    DONOR ||--o{ DONOR_CAMP : attends
    CAMP ||--o{ DONOR_CAMP : "registers"
    STAFF ||--o{ CAMP : coordinates
    DONOR ||--o{ DONATION : gives
    STAFF ||--o{ DONATION : collects
    CAMP |o--o{ DONATION : "hosts"
    DONATION ||--|{ BLOOD_UNIT : "separated into"
    COMPONENT_TYPE ||--o{ BLOOD_UNIT : "classifies"
    COMPONENT_TYPE ||--o{ STOCK_POLICY : "has level for"
    HOSPITAL ||--o{ REQUEST : places
    RECIPIENT ||--o{ REQUEST : "needs blood for"
    COMPONENT_TYPE ||--o{ REQUEST : "asks for"
    REQUEST ||--o{ ALLOCATION : "is met by"
    BLOOD_UNIT ||--o| ALLOCATION : "reserved in"
    BLOOD_UNIT ||--o{ UNIT_AUDIT : "history"

    PERSON { int person_id PK
             text full_name
             char sex
             date dob
             text city }
    DONOR { int person_id PK,FK
            blood_group blood_group
            date last_donation_date
            date deferred_until }
    RECIPIENT { int person_id PK,FK
                blood_group blood_group }
    STAFF { int person_id PK,FK
            text role }
    DONOR_PHONE { int donor_id PK,FK
                  text phone PK }
    DONOR_CAMP { int donor_id PK,FK
                 int camp_id PK,FK }
    CAMP { int camp_id PK
           text name
           text venue
           date camp_date
           int coordinator_id FK }
    DONATION { int donation_id PK
               int donor_id FK
               int camp_id FK
               int staff_id FK
               date donated_on
               int volume_ml
               text screening }
    COMPONENT_TYPE { component_code component PK
                     int shelf_days
                     text storage }
    BLOOD_UNIT { int unit_id PK
                 text barcode UK
                 int donation_id FK
                 component_code component FK
                 blood_group blood_group
                 date expiry_date
                 text status }
    HOSPITAL { int hospital_id PK
               text name UK
               text licence_no UK }
    REQUEST { int request_id PK
              int hospital_id FK
              int patient_id FK
              component_code component FK
              int units_needed
              text urgency
              text status }
    ALLOCATION { int allocation_id PK
                 int request_id FK
                 int unit_id UK,FK
                 timestamptz issued_at }
    STOCK_POLICY { blood_group blood_group PK
                   component_code component PK,FK
                   int reorder_level }
    STOCK_ALERT { int alert_id PK
                  blood_group blood_group
                  component_code component
                  int available }
    UNIT_AUDIT { bigint audit_id PK
                 int unit_id
                 text old_status
                 text new_status }
```

## Extended-ER features used

- **Specialization / generalization**: `PERSON` is the superclass of `DONOR`, `RECIPIENT` and `STAFF`. It is *overlapping* (a staff member can also be a donor) and *partial* (a person need not be any of them). Implemented as one table per subclass sharing the superclass key (the "reduction to relational schema" method for overlapping specialization).
- **Multivalued attributes**: a donor's phones and attended camps become `DONOR_PHONE` and `DONOR_CAMP`.
- **Weak-ish / dependent entity**: `BLOOD_UNIT` cannot exist without its `DONATION` (total participation, `UNIQUE(donation_id, component)`).
- **Derived attribute**: unit `expiry_date` and `blood_group` are computed by a trigger from `COMPONENT_TYPE.shelf_days` and the donor, then stored because a printed label must not change later.
- **Constraints**: cardinalities above, `CHECK` domains (`blood_group`, `component_code`), `UNIQUE(allocation.unit_id)` (a unit is allocated at most once), `UNIQUE(donor_id, donated_on)`.
