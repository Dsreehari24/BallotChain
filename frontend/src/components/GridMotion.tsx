import React, { useEffect, useRef, useState, useMemo } from 'react';

export interface GridMotionProps {
  items?: (string | React.ReactNode)[];
  gradientColor?: string;
  className?: string;
}

/**
 * React Bits — Grid Motion Component
 * 
 * Creates a subtle, technological 2D grid background with restrained motion.
 * Respects `prefers-reduced-motion` to ensure full accessibility.
 * Non-interfering (`pointer-events: none`, `aria-hidden="true"`).
 */
export const GridMotion: React.FC<GridMotionProps> = ({
  items,
  gradientColor = 'rgba(79, 70, 229, 0.06)',
  className = ''
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  // Check user preference for reduced motion
  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia) {
      const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
      setPrefersReducedMotion(mediaQuery.matches);

      const handler = (event: MediaQueryListEvent) => {
        setPrefersReducedMotion(event.matches);
      };

      mediaQuery.addEventListener('change', handler);
      return () => mediaQuery.removeEventListener('change', handler);
    }
  }, []);

  // Track pointer movements with smooth damping (only if reduced motion is disabled)
  useEffect(() => {
    if (prefersReducedMotion) return;

    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;
    let animationFrameId: number;

    const handlePointerMove = (e: MouseEvent) => {
      const { innerWidth, innerHeight } = window;
      // Normalized from -1 to 1
      const normX = (e.clientX / innerWidth - 0.5) * 2;
      const normY = (e.clientY / innerHeight - 0.5) * 2;

      // Restrained movement range (max 20px displacement)
      targetX = normX * 20;
      targetY = normY * 15;
    };

    const animate = () => {
      currentX += (targetX - currentX) * 0.08;
      currentY += (targetY - currentY) * 0.08;
      setOffset({ x: currentX, y: currentY });
      animationFrameId = requestAnimationFrame(animate);
    };

    window.addEventListener('mousemove', handlePointerMove, { passive: true });
    animationFrameId = requestAnimationFrame(animate);

    return () => {
      window.removeEventListener('mousemove', handlePointerMove);
      cancelAnimationFrame(animationFrameId);
    };
  }, [prefersReducedMotion]);

  // Default abstract cryptographic and network symbols (0 PII, high aesthetic value)
  const defaultItems = useMemo(() => [
    '⬡', '◈', '0x2A', '⛓', '✓', '◉', '🔒',
    'SHA-256', '⬢', 'GENESIS', '⚡', 'MERKLE', '◈', '0x8F',
    '⛓', 'PROOF', '⬡', 'ECDSA', '✓', '◈', 'BLOCK',
    '0x00', '🔒', 'VERIFIED', '⬢', 'NODE', '◉', 'BALLOT'
  ], []);

  const displayItems = items && items.length > 0 ? items : defaultItems;

  // 4 rows of 7 items
  const rowCount = 4;
  const colCount = 7;

  return (
    <div
      ref={containerRef}
      className={`fixed inset-0 overflow-hidden pointer-events-none select-none z-0 ${className}`}
      aria-hidden="true"
      style={{
        background: `radial-gradient(circle at 50% 30%, ${gradientColor}, transparent 70%)`
      }}
    >
      <div
        className="grid gap-4 w-[120vw] h-[120vh] -ml-[10vw] -mt-[10vh] transition-transform duration-100 ease-out"
        style={{
          gridTemplateRows: `repeat(${rowCount}, minmax(0, 1fr))`,
          gridTemplateColumns: `repeat(${colCount}, minmax(0, 1fr))`,
          transform: prefersReducedMotion
            ? 'none'
            : `translate3d(${offset.x}px, ${offset.y}px, 0)`,
          willChange: prefersReducedMotion ? 'auto' : 'transform'
        }}
      >
        {Array.from({ length: rowCount * colCount }).map((_, idx) => {
          const item = displayItems[idx % displayItems.length];
          return (
            <div
              key={idx}
              className="flex items-center justify-center rounded-xl border border-indigo-950/[0.04] bg-white/[0.25] backdrop-blur-[1px] p-4 text-xs font-mono font-medium text-slate-400/[0.45] shadow-[0_1px_3px_rgba(0,0,0,0.02)] transition-opacity duration-300"
            >
              {item}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default GridMotion;
