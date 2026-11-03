export type Approval = {
  id: number
  title: string
  subtitle: string
  description: string
}

export const mockApprovals: Approval[] = [
  {
    id: 1,
    title: 'Correct 4 prices in products',
    subtitle: 'PIM feed, batch of 12 Nov (validity)',
    description:
      'Prices 100× the usual (£1,999.00 vs £19.99): a decimal shift. Proposed fix: divide by 100.',
  },
  {
    id: 2,
    title: 'Merge 12 near-duplicate customers',
    subtitle: 'CRM feed (uniqueness)',
    description:
      'Same email once case and spaces are normalised; names spelt differently. Keeps the oldest record.',
  },
  {
    id: 3,
    title: 'Standardise 340 postcodes in customers',
    subtitle: 'CRM feed, batch of 12 Nov (validity)',
    description:
      'Safe-list fix, but it touches more than 200 rows, so it needs approval. Proposed fix: uppercase and add the missing space.',
  },
]