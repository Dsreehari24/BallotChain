import React from 'react';

export interface PocIslandProps {
  statusMessage?: string;
}

export const PocIsland: React.FC<PocIslandProps> = ({
  statusMessage = 'BallotChain UI island ready'
}) => {
  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 shadow-sm"
      role="status"
      aria-label="UI Island Status"
    >
      <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
      <span>{statusMessage}</span>
    </div>
  );
};

export default PocIsland;
