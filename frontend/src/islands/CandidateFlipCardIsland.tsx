import React, { useState, useEffect, useMemo, useCallback } from 'react';
import FlipCard from '../components/FlipCard';

export interface CandidatePartyItem {
  party_id: string;
  party_name: string;
  party_logo?: string;
  candidate_name?: string;
  candidate_profile_pic?: string;
}

export interface CandidateFlipCardIslandProps {
  parties: CandidatePartyItem[];
  fallbackSelector?: string;
}

export const CandidateFlipCardIsland: React.FC<CandidateFlipCardIslandProps> = ({
  parties,
  fallbackSelector = '#fallback-party-list'
}) => {
  const [filterQuery, setFilterQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Sync with the existing Django search input (#search) if present
  useEffect(() => {
    const searchInput = document.getElementById('search') as HTMLInputElement | null;
    if (searchInput) {
      const handleInput = (e: Event) => {
        setFilterQuery((e.target as HTMLInputElement).value.toLowerCase());
      };
      searchInput.addEventListener('input', handleInput);
      return () => {
        searchInput.removeEventListener('input', handleInput);
      };
    }
  }, []);

  // Hide the fallback list visually when island mounts, restore if unmounted
  useEffect(() => {
    const fallbackEl = document.querySelector(fallbackSelector) as HTMLElement | null;
    if (fallbackEl) {
      fallbackEl.style.display = 'none';
    }
    return () => {
      if (fallbackEl) {
        fallbackEl.style.display = '';
      }
    };
  }, [fallbackSelector]);

  // Handle candidate selection: delegate to fallback option for existing voting.js lifecycle
  const handleSelect = useCallback((candidateId: string) => {
    setSelectedId(candidateId);
    const fallbackOption = document.getElementById(candidateId);
    if (fallbackOption) {
      // 1. Trigger legacy option click handler to set 'selected' and append #vote
      fallbackOption.click();

      // 2. Trigger the legacy #vote button click to open confirmation/private-key dialog
      const voteBtn = document.getElementById('vote');
      if (voteBtn) {
        voteBtn.click();
      } else {
        setTimeout(() => {
          document.getElementById('vote')?.click();
        }, 30);
      }
    }
  }, []);

  // Filter candidates by search query
  const filteredCandidates = useMemo(() => {
    if (!filterQuery) return parties;
    return parties.filter((p) => {
      const name = (p.candidate_name || p.party_name).toLowerCase();
      return name.includes(filterQuery);
    });
  }, [parties, filterQuery]);

  if (!parties || parties.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-gray-500 bg-gray-50 rounded-lg border border-gray-200">
        No candidates currently registered for this ballot.
      </div>
    );
  }

  return (
    <div
      className="candidate-flipcard-grid flex flex-wrap justify-center gap-6 my-6 w-full max-w-5xl mx-auto"
      role="region"
      aria-label="Candidate Profile Cards"
    >
      {filteredCandidates.map((candidate) => {
        const displayName = candidate.candidate_name && candidate.candidate_name.trim().length > 0
          ? candidate.candidate_name
          : candidate.party_name;
        const hasProfilePic = Boolean(candidate.candidate_profile_pic && candidate.candidate_profile_pic.trim().length > 0);
        const profilePicSrc = hasProfilePic
          ? candidate.candidate_profile_pic!.startsWith('http') || candidate.candidate_profile_pic!.startsWith('/')
            ? candidate.candidate_profile_pic!
            : `/static/${candidate.candidate_profile_pic!}`
          : undefined;

        const isSelected = selectedId === candidate.party_id;

        return (
          <div key={candidate.party_id} className="relative flex flex-col items-center">
            <FlipCard
              width={260}
              height={320}
              radius={16}
              background="#ffffff"
              color="#1f2937"
              axis="y"
              flipOnClick={true}
              tilt={true}
              glare={true}
              ariaLabel={`Candidate profile for ${displayName}`}
              className={`border transition-all duration-200 ${
                isSelected ? 'ring-2 ring-indigo-600 shadow-md' : 'border-gray-200/90 shadow-sm'
              }`}
              front={
                <div className="flex flex-col items-center justify-between h-full p-5 text-center select-none bg-gradient-to-b from-white to-gray-50/50">
                  <div className="w-full flex items-center justify-between text-xs text-gray-400">
                    <span className="font-semibold text-indigo-600">Candidate #{candidate.party_id}</span>
                    <span className="text-[11px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                      Click to Flip
                    </span>
                  </div>

                  <div className="w-22 h-22 my-auto flex items-center justify-center p-2 rounded-2xl bg-indigo-50/60 border border-indigo-100/80">
                    {profilePicSrc ? (
                      <img
                        src={profilePicSrc}
                        alt={displayName}
                        className="w-18 h-18 rounded-full object-cover shadow-sm"
                        loading="lazy"
                      />
                    ) : (
                      <div className="w-18 h-18 rounded-full bg-white flex items-center justify-center text-indigo-600 shadow-sm">
                        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                          <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                      </div>
                    )}
                  </div>

                  <div className="w-full mt-auto">
                    <h4 className="text-base font-bold text-gray-900 truncate" title={displayName}>
                      {displayName}
                    </h4>
                    <p className="text-xs text-gray-500 font-medium truncate mt-0.5 text-indigo-600">
                      Certified Candidate
                    </p>
                    <div className="mt-3 text-[11px] font-semibold text-indigo-600 flex items-center justify-center gap-1">
                      <span>View Profile & Vote</span>
                      <span>→</span>
                    </div>
                  </div>
                </div>
              }
              back={
                <div className="flex flex-col items-center justify-between h-full p-5 text-center select-none bg-gradient-to-b from-indigo-50/40 via-white to-white">
                  <div className="w-full text-left">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-700">
                      Candidate Profile
                    </span>
                    <h4 className="text-base font-bold text-gray-900 truncate mt-1" title={displayName}>
                      {displayName}
                    </h4>
                  </div>

                  <div className="w-full my-auto text-left space-y-2 bg-gray-50/80 p-3 rounded-lg border border-gray-100 text-xs">
                    <div>
                      <span className="text-gray-400 block text-[10px] uppercase font-semibold">Candidate Status</span>
                      <span className="font-semibold text-gray-800">Certified Candidate</span>
                    </div>
                    <div>
                      <span className="text-gray-400 block text-[10px] uppercase font-semibold">Position</span>
                      <span className="font-medium text-gray-700">Representative</span>
                    </div>
                    <div>
                      <span className="text-gray-400 block text-[10px] uppercase font-semibold">Candidate ID</span>
                      <span className="font-mono text-gray-600">#{candidate.party_id}</span>
                    </div>
                  </div>

                  <div
                    className="w-full mt-auto pt-2"
                    onPointerDown={(e) => e.stopPropagation()}
                    onPointerUp={(e) => e.stopPropagation()}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      type="button"
                      data-no-flip="true"
                      onPointerDown={(e) => {
                        e.stopPropagation();
                      }}
                      onPointerUp={(e) => {
                        e.stopPropagation();
                      }}
                      onMouseDown={(e) => {
                        e.stopPropagation();
                      }}
                      onMouseUp={(e) => {
                        e.stopPropagation();
                      }}
                      onTouchStart={(e) => {
                        e.stopPropagation();
                      }}
                      onTouchEnd={(e) => {
                        e.stopPropagation();
                      }}
                      onKeyDown={(e) => {
                        e.stopPropagation();
                      }}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        handleSelect(candidate.party_id);
                      }}
                      className="w-full py-2 px-3 text-xs font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
                    >
                      {isSelected ? '✓ Proceed to Vote →' : 'Select Candidate & Vote'}
                    </button>
                  </div>
                </div>
              }
            />
          </div>
        );
      })}
    </div>
  );
};

export default CandidateFlipCardIsland;
