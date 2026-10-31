import React, { useMemo } from 'react';
import AnimatedList, { AnimatedListEntry } from '../components/AnimatedList';

export interface CandidateResultItem {
  sr?: number;
  rank?: number;
  candidate_name?: string;
  name?: string;
  party_name?: string;
  party_symbol?: string;
  affiliation?: string;
  position_title?: string;
  vote_count?: number;
  votes_received?: number;
  percentage?: number;
  is_winner?: boolean;
  is_nota?: boolean;
  status?: string;
}

export interface CandidateRosterIslandProps {
  results: CandidateResultItem[];
  title?: string;
}

export const CandidateRosterIsland: React.FC<CandidateRosterIslandProps> = ({
  results,
  title = 'Verified Candidate Standings'
}) => {
  // Detect system reduced-motion preference
  const prefersReducedMotion = useMemo(() => {
    if (typeof window !== 'undefined' && window.matchMedia) {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    return false;
  }, []);

  // Map server results to AnimatedList items
  const items: AnimatedListEntry[] = useMemo(() => {
    return results.map((res, index) => {
      const rank = res.rank ?? res.sr ?? index + 1;
      const isNota = !!res.is_nota || (res.party_name && res.party_name.trim().toUpperCase().includes('NOTA')) || false;
      const candName = res.candidate_name || res.party_name || res.name || (isNota ? 'None of the Above (NOTA)' : `Candidate ${rank}`);
      const voteCount = res.votes_received ?? res.vote_count ?? 0;
      const pct = typeof res.percentage === 'number' ? res.percentage : 0;
      const formattedPct = `${pct.toFixed(1)}%`;
      const voteText = `${voteCount.toLocaleString()} ${voteCount === 1 ? 'vote' : 'votes'}`;
      const standingSummary = `${candName} — ${voteText} — ${formattedPct}`;

      const imageSrc = !isNota && res.party_symbol
        ? res.party_symbol.startsWith('http') || res.party_symbol.startsWith('/')
          ? res.party_symbol
          : `/static/${res.party_symbol}`
        : undefined;

      const rankBadge = (
        <span
          className={`flex items-center justify-center w-8 h-8 rounded-full text-xs font-bold border ${
            res.is_winner
              ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
              : isNota
              ? 'bg-slate-100 text-slate-600 border-slate-300'
              : 'bg-indigo-50 text-indigo-700 border-indigo-200'
          }`}
          aria-hidden="true"
        >
          {isNota ? 'Ø' : `#${rank}`}
        </span>
      );

      const titleNode = (
        <span className="flex items-center gap-2 flex-wrap" data-candidate-name={candName}>
          <span className="font-semibold text-gray-900">{candName}</span>
          {res.is_winner && (
            <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase rounded bg-emerald-100 text-emerald-800 border border-emerald-300">
              Elected
            </span>
          )}
          {isNota && (
            <span className="px-1.5 py-0.5 text-[10px] font-bold uppercase rounded bg-slate-100 text-slate-700 border border-slate-300">
              NOTA
            </span>
          )}
          <span className="sr-only">{standingSummary}</span>
        </span>
      );

      const descNode = (
        <span className="text-xs text-gray-500">
          Rank #{rank}
          {res.position_title ? ` • ${res.position_title}` : ''}
          {res.affiliation ? ` • ${res.affiliation}` : isNota ? ' • None of the Above' : ''}
        </span>
      );

      const metaNode = (
        <span
          className="font-medium text-gray-700 whitespace-nowrap text-sm"
          title={standingSummary}
          data-standing={standingSummary}
        >
          {voteText} &mdash; {formattedPct}
        </span>
      );

      return {
        id: `candidate-${rank}-${res.candidate_name || res.party_name || index}`,
        title: titleNode,
        description: descNode,
        meta: metaNode,
        icon: !imageSrc ? rankBadge : undefined,
        image: imageSrc,
      };
    });
  }, [results]);

  if (!results || results.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-gray-500 bg-gray-50 rounded-lg border border-gray-200">
        No candidate results currently recorded.
      </div>
    );
  }

  return (
    <div className="candidate-roster-island w-full max-w-xl mx-auto my-4" aria-label={title}>
      <div className="flex items-center justify-between mb-3 px-1">
        <h3 className="text-sm font-bold uppercase tracking-wider text-gray-700">
          {title}
        </h3>
        <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
          {results.length} {results.length === 1 ? 'Contender' : 'Contenders'}
        </span>
      </div>

      <AnimatedList
        items={items}
        animation={prefersReducedMotion ? 'none' : 'pop'}
        animateOnce={true}
        theme="light"
        accentColor="#4f46e5"
        enableArrowNavigation={true}
        selectOnHover={true}
        displayScrollbar={true}
        frame={true}
        maxHeight={460}
        radius={10}
        gap={8}
        className="shadow-sm border border-gray-200/80 rounded-xl overflow-hidden"
      />

      <p className="text-[11px] text-gray-400 mt-2 text-center" aria-hidden="true">
        Verified official standings certified via distributed ledger consensus.
      </p>
    </div>
  );
};

export default CandidateRosterIsland;
