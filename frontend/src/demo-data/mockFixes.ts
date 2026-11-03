export type FixStatus =
  | 'applied'
  | 'awaiting_approval'
  | 'approved'
  | 'rejected'
  | 'undone'

export type Fix = {
  fix_id: number
  day: number
  table_name: string
  column_name: string
  fix_type: string
  record_id: string
  before_value: string
  after_value: string
  reasoning: string
  status: FixStatus
}

export const FIX_TYPE: Record<string, string> = {
  normalise_case: 'Fixed text case',
  standardise_date: 'Standardised date',
  map_column: 'Renamed column back',
  correct_price: 'Corrected price',
  fill_from_other_source: 'Filled missing value',
  merge_customers: 'Merged customers',
  quarantine_duplicate: 'Quarantined duplicate',
}

export const FIX_STATUS: Record<FixStatus, string> = {
  applied: 'Applied',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  rejected: 'Rejected',
  undone: 'Undone',
}

export const mockFixes: Fix[] = [
  {
    fix_id: 1,
    day: 3,
    table_name: 'customers',
    column_name: 'email',
    fix_type: 'normalise_case',
    record_id: 'C-00412',
    before_value: 'Marie.Dupont@Mail.COM ',
    after_value: 'marie.dupont@mail.com',
    reasoning: 'Safe-list fix: trailing space removed and email lowercased. No information lost.',
    status: 'applied',
  },
  {
    fix_id: 2,
    day: 3,
    table_name: 'orders',
    column_name: 'order_ts',
    fix_type: 'standardise_date',
    record_id: 'O-90231',
    before_value: '03/11/2026 14:02',
    after_value: '2026-11-03 14:02:00',
    reasoning: 'Date format differs from the usual ISO format used in this feed; converted automatically.',
    status: 'applied',
  },
  {
    fix_id: 3,
    day: 5,
    table_name: 'orders',
    column_name: 'quantity',
    fix_type: 'map_column',
    record_id: 'batch 18',
    before_value: 'item_count',
    after_value: 'quantity',
    reasoning: 'Column item_count holds small integers matching the usual quantity distribution; renamed upstream. Mapping is clear enough to apply.',
    status: 'applied',
  },
  {
    fix_id: 4,
    day: 6,
    table_name: 'products',
    column_name: 'unit_price',
    fix_type: 'correct_price',
    record_id: 'SKU-0482',
    before_value: '£1,999.00',
    after_value: '19.99',
    reasoning: 'Price is 100× the catalogue price for this SKU: probable decimal shift. Out-of-range correction needs human approval.',
    status: 'awaiting_approval',
  },
  {
    fix_id: 5,
    day: 7,
    table_name: 'customers',
    column_name: 'email',
    fix_type: 'fill_from_other_source',
    record_id: 'C-01877',
    before_value: '(null)',
    after_value: 'l.martin@mail.com',
    reasoning: 'Email missing in CRM batch; the same customer placed a web order carrying this email.',
    status: 'approved',
  },
  {
    fix_id: 6,
    day: 8,
    table_name: 'customers',
    column_name: 'name',
    fix_type: 'merge_customers',
    record_id: 'C-00310 / C-02211',
    before_value: 'Jon Smith / John Smyth',
    after_value: 'John Smith',
    reasoning: 'Same email and phone once normalised, but the two people could share a household. Merge was proposed for review.',
    status: 'rejected',
  },
  {
    fix_id: 7,
    day: 9,
    table_name: 'orders',
    column_name: 'order_id',
    fix_type: 'quarantine_duplicate',
    record_id: 'O-90455',
    before_value: 'pending',
    after_value: 'quarantined',
    reasoning: 'Exact duplicate of another row in the same batch: extra copy moved to quarantine, never deleted.',
    status: 'undone',
  },
]