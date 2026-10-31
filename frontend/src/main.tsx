import React from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { PocIsland } from './islands/PocIsland';
import { CandidateRosterIsland, CandidateResultItem } from './islands/CandidateRosterIsland';
import { OtpCodeSlotsIsland } from './islands/OtpCodeSlotsIsland';
import { CandidateFlipCardIsland, CandidatePartyItem } from './islands/CandidateFlipCardIsland';
import { SlideCommitIsland } from './islands/SlideCommitIsland';
import { BlockchainLedgerIsland, BlockchainLedgerProps } from './islands/BlockchainLedgerIsland';
import { GridMotionIsland } from './islands/GridMotionIsland';

// Track mounted roots to prevent duplicate mounting
const mountedRoots = new WeakMap<HTMLElement, boolean>();

/**
 * Progressive Island Mounting Engine
 * 
 * Inspects the DOM for designated BallotChain island containers.
 * Mounts React components into isolated containers without interfering
 * with Django's native page lifecycle, session auth, or forms.
 */
function mountIslands() {
  // 1. Proof of Concept Island
  const pocRoot = document.getElementById('ballotchain-poc-island-root');
  if (pocRoot && !mountedRoots.has(pocRoot)) {
    try {
      mountedRoots.set(pocRoot, true);
      const statusMessage = pocRoot.getAttribute('data-status-message') || 'BallotChain UI island ready';
      const root = createRoot(pocRoot);
      root.render(
        <React.StrictMode>
          <PocIsland statusMessage={statusMessage} />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount PoC island:', err);
    }
  }

  // 2. Animated List Candidate Roster Island
  const rosterRoot = document.getElementById('ballotchain-roster-island-root');
  if (rosterRoot && !mountedRoots.has(rosterRoot)) {
    try {
      mountedRoots.set(rosterRoot, true);
      const dataScript = document.getElementById('ballotchain-results-data');
      let results: CandidateResultItem[] = [];
      if (dataScript && dataScript.textContent) {
        results = JSON.parse(dataScript.textContent);
      }
      const root = createRoot(rosterRoot);
      root.render(
        <React.StrictMode>
          <CandidateRosterIsland results={results} />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount Animated List Candidate Roster island:', err);
    }
  }

  // 3. Code Slots OTP Island
  const otpRoot = document.getElementById('ballotchain-otp-island-root');
  if (otpRoot && !mountedRoots.has(otpRoot)) {
    try {
      mountedRoots.set(otpRoot, true);
      const root = createRoot(otpRoot);
      root.render(
        <React.StrictMode>
          <OtpCodeSlotsIsland />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount Code Slots OTP island:', err);
    }
  }

  // 4. Flip Card Candidate Profile Island
  const cardRoot = document.getElementById('ballotchain-candidate-cards-island-root');
  if (cardRoot && !mountedRoots.has(cardRoot)) {
    try {
      mountedRoots.set(cardRoot, true);
      const dataScript = document.getElementById('ballotchain-parties-data');
      let parties: CandidatePartyItem[] = [];
      if (dataScript && dataScript.textContent) {
        parties = JSON.parse(dataScript.textContent);
      }
      const root = createRoot(cardRoot);
      root.render(
        <React.StrictMode>
          <CandidateFlipCardIsland parties={parties} />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount Candidate Flip Card island:', err);
    }
  }

  // 5. Slide Commit Ballot Submission Island
  const slideRoot = document.getElementById('ballotchain-slide-commit-island-root');
  if (slideRoot && !mountedRoots.has(slideRoot)) {
    try {
      mountedRoots.set(slideRoot, true);
      const root = createRoot(slideRoot);
      root.render(
        <React.StrictMode>
          <SlideCommitIsland />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount Slide Commit Ballot Submission island:', err);
    }
  }

  // 6. Shared Blockchain Ledger Explorer Island (React Bits Cubes)
  const ledgerRoot = document.getElementById('ballotchain-ledger-island-root');
  if (ledgerRoot && !mountedRoots.has(ledgerRoot)) {
    try {
      mountedRoots.set(ledgerRoot, true);
      const dataScript = document.getElementById('ballotchain-ledger-data');
      let ledgerData: BlockchainLedgerProps = {
        blocks: [],
        totalBlocks: 0,
        totalVotes: 0,
        currentPage: 1,
        totalPages: 1
      };
      if (dataScript && dataScript.textContent) {
        ledgerData = JSON.parse(dataScript.textContent);
      }
      const root = createRoot(ledgerRoot);
      root.render(
        <React.StrictMode>
          <BlockchainLedgerIsland {...ledgerData} />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount Blockchain Ledger island:', err);
    }
  }

  // 7. Grid Motion Background Island
  const gridMotionRoot = document.getElementById('ballotchain-grid-motion-root');
  if (gridMotionRoot && !mountedRoots.has(gridMotionRoot)) {
    try {
      mountedRoots.set(gridMotionRoot, true);
      const root = createRoot(gridMotionRoot);
      root.render(
        <React.StrictMode>
          <GridMotionIsland />
        </React.StrictMode>
      );
    } catch (err) {
      console.warn('[BallotChain Island] Failed to mount Grid Motion island:', err);
    }
  }
}

// Global hook for dynamic mounting
(window as unknown as { mountBallotChainIslands?: () => void }).mountBallotChainIslands = mountIslands;

// Initial execution
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mountIslands);
} else {
  mountIslands();
}

// Observe DOM mutations to automatically hydrate dynamically injected AJAX snippets (e.g. candidate_details.html, voting.html)
if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
  const observer = new MutationObserver(() => {
    mountIslands();
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  }
}
