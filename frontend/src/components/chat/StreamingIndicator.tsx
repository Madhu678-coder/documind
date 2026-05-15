import { motion } from 'framer-motion';

export function StreamingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-4 py-3" aria-label="Assistant is typing">
      {[0, 0.15, 0.3].map((delay, i) => (
        <motion.span
          key={i}
          className="h-2 w-2 rounded-full bg-[var(--dm-primary)]"
          animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
          transition={{ duration: 1, delay, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}
    </div>
  );
}
