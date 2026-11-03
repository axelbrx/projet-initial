import { motion, useReducedMotion } from 'motion/react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type KpiCardProps = {
  title: string
  value: string | number
  // Sets the KPI type of value, to determine how is it displayed
  type: 'number' | 'percentage' | 'string'
}

// Parent: décale l'apparition de chaque lettre
const container = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.04 } },
}

// Enfant: fade in + léger slide up
const letter = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.25, ease: 'easeOut' as const },
  },
}

export function KpiCard({ title, value, type }: KpiCardProps) {
  const reduceMotion = useReducedMotion()

  // Format the value based on the type
  const formattedValue = String(
    type === 'percentage'
      ? `${value} %`
      : type === 'number' && typeof value === 'number'
        ? new Intl.NumberFormat('fr-FR').format(value)
        : value,
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {reduceMotion ? (
          <p className="text-3xl font-semibold">{formattedValue}</p>
        ) : (
          <motion.p
            // La key change avec la valeur: l'animation est rejouée à chaque update
            key={formattedValue}
            className="text-3xl font-semibold"
            variants={container}
            initial="hidden"
            animate="visible"
            aria-label={formattedValue}
          >
            {Array.from(formattedValue).map((char, i) => (
              <motion.span
                key={i}
                variants={letter}
                className="inline-block whitespace-pre"
                aria-hidden="true"
              >
                {char}
              </motion.span>
            ))}
          </motion.p>
        )}
      </CardContent>
    </Card>
  )
}