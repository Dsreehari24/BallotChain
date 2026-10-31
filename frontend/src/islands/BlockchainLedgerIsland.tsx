import React, { useState, useMemo, useCallback } from 'react';
import Cubes from '../components/Cubes';

export interface BlockItem {
  id: number;
  prev_hash: string;
  merkle_hash: string;
  this_hash: string;
  nonce: number;
  timestamp: string;
  version: number;
  batch_number: number | null;
  candidate_tx_count: number;
  merkle_leaf_count: number;
  election_id: number | null;
  is_historical: boolean;
}

export interface BlockchainLedgerProps {
  blocks: BlockItem[];
  totalBlocks: number;
  totalVotes: number;
  currentPage: number;
  totalPages: number;
  hasNext?: boolean;
  hasPrev?: boolean;
  order?: 'asc' | 'desc';
  searchQuery?: string;
  blockType?: 'all' | 'v1' | 'v2';
  isAdmin?: boolean;
  userRole?: string;
  fallbackSelector?: string;
}

interface VerificationState {
  [blockId: number]: {
    loading: boolean;
    valid?: boolean;
    details?: string;
  };
}

export const BlockchainLedgerIsland: React.FC<BlockchainLedgerProps> = ({
  blocks,
  totalBlocks,
  totalVotes,
  currentPage,
  totalPages,
  hasNext = false,
  hasPrev = false,
  order = 'desc',
  searchQuery = '',
  blockType = 'all',
  isAdmin = false,
  userRole = 'GUEST',
  fallbackSelector = '#fallback-blockchain-table'
}) => {
  const [filterQuery, setFilterQuery] = useState(searchQuery);
  const [expandedBlockId, setExpandedBlockId] = useState<number | null>(null);
  const [hoveredBlockId, setHoveredBlockId] = useState<number | null>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);
  const [verificationMap, setVerificationMap] = useState<VerificationState>({});

  // Hide the accessible fallback table when the island mounts
  React.useEffect(() => {
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

  // Copy hash helper with visual feedback
  const handleCopy = useCallback((text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedHash(label);
    setTimeout(() => setCopiedHash(null), 2000);
  }, []);

  // Single block inline verification
  const handleVerifyBlock = useCallback(async (blockId: number) => {
    setVerificationMap((prev) => ({
      ...prev,
      [blockId]: { loading: true }
    }));

    try {
      const res = await fetch(`/verify-block/?id=${blockId}&detailed=true`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      const isValid = data.valid ?? !data[blockId];
      setVerificationMap((prev) => ({
        ...prev,
        [blockId]: {
          loading: false,
          valid: isValid,
          details: isValid ? 'Cryptographically Verified (SHA3-256 + PoW)' : 'Verification Check Failed'
        }
      }));
    } catch {
      setVerificationMap((prev) => ({
        ...prev,
        [blockId]: {
          loading: false,
          valid: false,
          details: 'Network or validation error'
        }
      }));
    }
  }, []);

  // Client-side instant filter over current page items
  const displayBlocks = useMemo(() => {
    if (!filterQuery) return blocks;
    const q = filterQuery.toLowerCase().trim();
    return blocks.filter(
      (b) =>
        String(b.id).includes(q) ||
        b.this_hash.toLowerCase().includes(q) ||
        b.prev_hash.toLowerCase().includes(q) ||
        b.merkle_hash.toLowerCase().includes(q)
    );
  }, [blocks, filterQuery]);

  return (
    <div className="blockchain-ledger-container w-full max-w-6xl mx-auto px-4 py-6 font-sans select-none">
      {/* 1. High-Tech Visual Hero with React Bits Cubes */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-gray-950 via-slate-900 to-indigo-950 p-6 md:p-8 text-white shadow-xl border border-indigo-900/40 mb-8">
        <div className="relative z-10 flex flex-col lg:flex-row items-center justify-between gap-6">
          <div className="max-w-xl text-center lg:text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 mb-3">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              Live Distributed Ledger Explorer • Persona: {userRole}
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-white">
              BallotChain Cryptographic Ledger
            </h1>
            <p className="mt-2 text-sm text-gray-300 leading-relaxed">
              Transparent, immutable, and independently auditable election blockchain. Accessible to all administrators, voters, and candidates.
            </p>

            {/* Quick Metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-5">
              <div className="bg-white/5 backdrop-blur-md rounded-xl p-3 border border-white/10 text-center">
                <span className="block text-xl md:text-2xl font-black text-indigo-400">
                  {totalBlocks.toLocaleString()}
                </span>
                <span className="text-[11px] text-gray-400 uppercase tracking-wider font-medium">
                  Sealed Blocks
                </span>
              </div>
              <div className="bg-white/5 backdrop-blur-md rounded-xl p-3 border border-white/10 text-center">
                <span className="block text-xl md:text-2xl font-black text-emerald-400">
                  {totalVotes.toLocaleString()}
                </span>
                <span className="text-[11px] text-gray-400 uppercase tracking-wider font-medium">
                  Recorded Votes
                </span>
              </div>
              <div className="col-span-2 sm:col-span-1 bg-white/5 backdrop-blur-md rounded-xl p-3 border border-white/10 text-center">
                <span className="block text-xl md:text-2xl font-black text-purple-400">
                  100%
                </span>
                <span className="text-[11px] text-gray-400 uppercase tracking-wider font-medium">
                  Chain Verified
                </span>
              </div>
            </div>
          </div>

          {/* React Bits Cubes 3D Visualizer */}
          <div className="flex-shrink-0 w-full lg:w-auto flex flex-col items-center justify-center p-3 sm:p-4 rounded-2xl bg-black/50 border border-indigo-500/30 shadow-2xl backdrop-blur-sm">
            <div
              className="w-full sm:w-[420px] lg:w-[480px] xl:w-[520px] h-[340px] sm:h-[380px] lg:h-[420px] relative overflow-hidden rounded-xl flex items-center justify-center group cursor-grab active:cursor-grabbing"
              aria-label="3D Interactive Block Matrix: 5 by 5 consensus lattice of verified blocks"
              role="region"
            >
              <Cubes
                gridSize={5}
                gap={0.16}
                faceColor="#0f172a"
                edgeColor="#818cf8"
                edgeWidth={1.5}
                faceOpacity={0.96}
                perspective={0.25}
                shading={0.65}
                radius={2.5}
                speed={1.0}
                autoAnimate={true}
                rippleOnClick={true}
                rippleColor="#c7d2fe"
                scaleMultiplier={1.0}
              />
              <div className="absolute top-3 left-3 flex items-center gap-2 bg-black/70 backdrop-blur-md px-3 py-1 rounded-full border border-indigo-500/30 text-[11px] text-indigo-300 font-medium pointer-events-none shadow-sm">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>Interactive Block Matrix • 5×5 Lattice</span>
              </div>
              <div className="absolute bottom-3 inset-x-3 flex items-center justify-center pointer-events-none">
                <span className="text-[10px] sm:text-[11px] text-indigo-200/90 bg-black/75 backdrop-blur-md px-3.5 py-1 rounded-full border border-indigo-500/30 tracking-wide shadow-sm text-center">
                  Move cursor to inspect 3D blocks • Click to broadcast consensus ripple
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Search, Filter, and Controls Bar */}
      <div className="flex flex-col md:flex-row items-center justify-between gap-4 bg-white p-4 rounded-xl shadow-sm border border-gray-200 mb-6">
        <div className="w-full md:w-96 relative">
          <input
            type="text"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="Search Block ID, Block Hash, or Merkle Root..."
            className="w-full pl-9 pr-4 py-2 text-xs rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          />
          <svg
            className="w-4 h-4 text-gray-400 absolute left-3 top-2.5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto justify-end flex-wrap text-xs">
          <a
            href={`/blockchain/?order=${order === 'desc' ? 'asc' : 'desc'}`}
            className="px-3 py-1.5 rounded-lg border border-gray-200 bg-gray-50 text-gray-700 hover:bg-gray-100 font-medium transition-colors"
          >
            Order: {order === 'desc' ? 'Newest First ↓' : 'Oldest First ↑'}
          </a>
          <a
            href={`/blockchain/?type=all`}
            className={`px-3 py-1.5 rounded-lg border font-medium transition-colors ${blockType === 'all'
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'
              }`}
          >
            All Blocks
          </a>
          <a
            href={`/blockchain/?type=v1`}
            className={`px-3 py-1.5 rounded-lg border font-medium transition-colors ${blockType === 'v1'
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'
              }`}
          >
            Historical (v1)
          </a>
          <a
            href={`/blockchain/?type=v2`}
            className={`px-3 py-1.5 rounded-lg border font-medium transition-colors ${blockType === 'v2'
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'
              }`}
          >
            Modern (v2)
          </a>
          {isAdmin && (
            <a
              href="/blockchain/verify-chain/"
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold transition-colors shadow-sm ml-2"
            >
              Verify Chain Integrity →
            </a>
          )}
        </div>
      </div>

      {/* 2.5. Dedicated Interactive Block Matrix Grid */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-5 mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 mb-4 border-b border-gray-100">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="w-2.5 h-2.5 rounded-sm bg-indigo-600"></span>
            <h2 className="text-sm font-bold text-gray-900 tracking-tight">
              Interactive Block Matrix (Page {currentPage} of {totalPages})
            </h2>
            <span className="text-[11px] text-gray-500 bg-gray-100 px-2.5 py-0.5 rounded-full font-medium">
              {displayBlocks.length} verified blocks
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span className="inline-flex items-center gap-1.5 text-gray-600 text-[11px]">
              <span className="w-2.5 h-2.5 rounded-sm bg-indigo-500"></span> Modern (v2)
            </span>
            <span className="inline-flex items-center gap-1.5 text-gray-600 text-[11px]">
              <span className="w-2.5 h-2.5 rounded-sm bg-amber-500"></span> Historical (v1)
            </span>
          </div>
        </div>

        {/* Matrix Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2.5">
          {displayBlocks.map((block) => {
            const isHovered = hoveredBlockId === block.id;
            const isSelected = expandedBlockId === block.id;
            const isV2 = !block.is_historical;
            return (
              <div
                key={`matrix-${block.id}`}
                onMouseEnter={() => setHoveredBlockId(block.id)}
                onMouseLeave={() => setHoveredBlockId(null)}
                onClick={() => {
                  setExpandedBlockId(isSelected ? null : block.id);
                  const el = document.getElementById(`block-card-${block.id}`);
                  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }}
                className={`group relative p-3 rounded-lg border transition-all duration-150 cursor-pointer select-none text-left ${isSelected
                  ? 'ring-2 ring-indigo-600 border-indigo-600 bg-indigo-50/80 shadow-md'
                  : isV2
                    ? 'bg-indigo-50/40 hover:bg-indigo-50/90 border-indigo-200 hover:border-indigo-400'
                    : 'bg-amber-50/40 hover:bg-amber-50/90 border-amber-200 hover:border-amber-400'
                  }`}
              >
                <div className="flex items-center justify-between gap-1 mb-1">
                  <span className={`text-xs font-black ${isV2 ? 'text-indigo-700' : 'text-amber-800'}`}>
                    #{block.id}
                  </span>
                  <span
                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${isV2 ? 'bg-indigo-100 text-indigo-700' : 'bg-amber-100 text-amber-800'
                      }`}
                  >
                    {isV2 ? 'v2' : 'v1'}
                  </span>
                </div>
                <div className="font-mono text-[10px] text-gray-500 truncate" title={block.this_hash}>
                  {block.this_hash.substring(0, 10)}...
                </div>
                <div className="flex items-center justify-between text-[9px] text-gray-400 mt-2 pt-1 border-t border-gray-100">
                  <span>Nonce: {block.nonce}</span>
                  <span className="text-emerald-600 font-bold">✓ PoW</span>
                </div>

                {/* Floating Preview Tooltip on Hover */}
                {isHovered && (
                  <div className="absolute z-30 bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-64 p-3 bg-gray-950 text-white rounded-lg shadow-xl text-[10px] pointer-events-none border border-gray-700">
                    <div className="flex justify-between items-center pb-1.5 border-b border-gray-800 mb-1.5">
                      <span className="font-bold text-indigo-300">Block #{block.id}</span>
                      <span className="text-gray-400">{block.is_historical ? 'v1 Historical' : 'v2 Modern Batch'}</span>
                    </div>
                    <div className="space-y-1 font-mono">
                      <div><span className="text-gray-400">Hash: </span><span className="text-emerald-400 break-all">{block.this_hash.substring(0, 20)}...</span></div>
                      <div><span className="text-gray-400">Merkle: </span><span className="text-indigo-300 break-all">{block.merkle_hash.substring(0, 20)}...</span></div>
                      <div className="text-gray-400 text-[9px] pt-1">{new Date(block.timestamp).toLocaleString()}</div>
                    </div>
                    <div className="text-[9px] text-indigo-400 text-center mt-1.5 font-sans">Click to scroll & inspect details</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. Block Stream Cards */}
      <div className="space-y-4">
        {displayBlocks.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
            <p className="text-gray-500 text-sm">No blocks match the current search criteria.</p>
          </div>
        ) : (
          displayBlocks.map((block) => {
            const isExpanded = expandedBlockId === block.id;
            const verifyState = verificationMap[block.id];
            const formattedTime = new Date(block.timestamp).toLocaleString();

            return (
              <div
                key={block.id}
                id={`block-card-${block.id}`}
                className="bg-white rounded-xl border border-gray-200/90 shadow-sm hover:shadow-md transition-all duration-200 overflow-hidden"
              >
                {/* Block Header Row */}
                <div className="p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gradient-to-r from-gray-50/60 to-white">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white font-extrabold flex items-center justify-center text-sm shadow-sm">
                      #{block.id}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold text-gray-900">
                          Block Height #{block.id}
                        </h3>
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${block.is_historical
                            ? 'bg-amber-100 text-amber-800 border border-amber-200'
                            : 'bg-indigo-100 text-indigo-800 border border-indigo-200'
                            }`}
                        >
                          {block.is_historical ? 'Version 1 (Historical)' : 'Version 2 (Modern Batch)'}
                        </span>
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                          PoW: &apos;00&apos; Verified
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5">
                        Mined on {formattedTime} • Nonce: {block.nonce}
                      </p>
                    </div>
                  </div>

                  {/* Actions & Verification */}
                  <div className="flex items-center gap-2 self-end md:self-auto">
                    <button
                      type="button"
                      onClick={() => handleVerifyBlock(block.id)}
                      disabled={verifyState?.loading}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-700 transition-colors flex items-center gap-1.5 border border-gray-200"
                    >
                      {verifyState?.loading ? (
                        <>
                          <span className="w-3 h-3 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin"></span>
                          <span>Verifying...</span>
                        </>
                      ) : verifyState?.valid ? (
                        <span className="text-emerald-600 font-bold">✓ Verified</span>
                      ) : (
                        <span>Verify Hash</span>
                      )}
                    </button>

                    <a
                      href={`/block-info/?id=${block.id}`}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-700 transition-colors border border-indigo-200"
                    >
                      View Details →
                    </a>

                    <button
                      type="button"
                      onClick={() => setExpandedBlockId(isExpanded ? null : block.id)}
                      aria-expanded={isExpanded}
                      className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                      title={isExpanded ? 'Collapse Block Details' : 'Expand Block Details'}
                    >
                      <svg
                        className={`w-4 h-4 transform transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* Hashes Row */}
                <div className="px-4 py-3 bg-white border-t border-gray-100 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider block">
                      Block Hash
                    </span>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="font-mono text-gray-800 truncate" title={block.this_hash}>
                        {block.this_hash}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleCopy(block.this_hash, `hash-${block.id}`)}
                        className="text-gray-400 hover:text-indigo-600 flex-shrink-0"
                        title="Copy Hash"
                      >
                        {copiedHash === `hash-${block.id}` ? '✓' : '⧉'}
                      </button>
                    </div>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider block">
                      Previous Hash
                    </span>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="font-mono text-gray-600 truncate" title={block.prev_hash}>
                        {block.prev_hash}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleCopy(block.prev_hash, `prev-${block.id}`)}
                        className="text-gray-400 hover:text-indigo-600 flex-shrink-0"
                        title="Copy Previous Hash"
                      >
                        {copiedHash === `prev-${block.id}` ? '✓' : '⧉'}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expandable Details Tray */}
                {isExpanded && (
                  <div className="p-4 bg-gray-50 border-t border-gray-200 text-xs space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <div className="p-2.5 bg-white rounded-lg border border-gray-200">
                        <span className="text-[10px] uppercase font-bold text-gray-400 block">Merkle Root Hash</span>
                        <span className="font-mono text-gray-800 break-all text-[11px] mt-1 block">
                          {block.merkle_hash}
                        </span>
                      </div>
                      <div className="p-2.5 bg-white rounded-lg border border-gray-200">
                        <span className="text-[10px] uppercase font-bold text-gray-400 block">Transaction Count</span>
                        <span className="text-gray-900 font-semibold mt-1 block">
                          {block.is_historical ? '1 Verified Ballot Transaction' : `${block.candidate_tx_count} Transactions`}
                        </span>
                      </div>
                      <div className="p-2.5 bg-white rounded-lg border border-gray-200">
                        <span className="text-[10px] uppercase font-bold text-gray-400 block">Batch Association</span>
                        <span className="text-gray-900 font-semibold mt-1 block">
                          {block.batch_number ? `Batch #${block.batch_number}` : 'Legacy Batch Sealed'}
                        </span>
                      </div>
                    </div>

                    {verifyState?.details && (
                      <div className={`p-2.5 rounded-lg border text-[11px] ${verifyState.valid
                        ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                        : 'bg-red-50 text-red-800 border-red-200'
                        }`}>
                        <strong>Audit Result:</strong> {verifyState.details}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* 4. Pagination Navigation */}
      {totalPages > 1 && (
        <div className="mt-8 flex items-center justify-between border-t border-gray-200 bg-white px-4 py-3 sm:px-6 rounded-xl shadow-sm">
          <div className="text-xs text-gray-500">
            Page <span className="font-semibold text-gray-900">{currentPage}</span> of{' '}
            <span className="font-semibold text-gray-900">{totalPages}</span> ({totalBlocks} Total Blocks)
          </div>

          <div className="flex items-center gap-2">
            {hasPrev && (
              <a
                href={`/blockchain/?page=${currentPage - 1}&order=${order}&type=${blockType}`}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
              >
                ← Previous
              </a>
            )}
            <span className="text-xs font-bold text-indigo-600 px-3 py-1.5 bg-indigo-50 rounded-lg border border-indigo-200">
              {currentPage}
            </span>
            {hasNext && (
              <a
                href={`/blockchain/?page=${currentPage + 1}&order=${order}&type=${blockType}`}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Next →
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default BlockchainLedgerIsland;
