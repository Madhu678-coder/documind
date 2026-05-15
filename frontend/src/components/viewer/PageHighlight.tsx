import { motion } from 'framer-motion';

interface PageHighlightProps {
  /** Whether to show the highlight overlay */
  active: boolean;
}

/**
 * Renders an animated highlight overlay on the current PDF page.
 * Place this as a sibling/overlay to the react-pdf Page component.
 */
export function PageHighlight({ active }: PageHighlightProps) {
  if (!active) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      className="pointer-events-none absolute inset-0 rounded border-2 border-[var(--dm-accent)] bg-[var(--dm-accent)]/10"
      aria-hidden
    />
  );
}
