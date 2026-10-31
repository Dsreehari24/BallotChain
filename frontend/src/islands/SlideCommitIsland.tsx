import React, { useCallback, useEffect, useState } from 'react';
import SlideCommit from '../components/SlideCommit';

export interface SlideCommitIslandProps {
  confirmSelector?: string;
  keySelector?: string;
}

export const SlideCommitIsland: React.FC<SlideCommitIslandProps> = ({
  confirmSelector = '#final-confirm',
  keySelector = '#private-key-input'
}) => {
  const [disabled] = useState(false);

  // When island mounts, visually hide the fallback confirm button so voter uses the slider
  useEffect(() => {
    const confirmBtn = document.querySelector(confirmSelector) as HTMLElement | null;
    if (confirmBtn) {
      confirmBtn.style.display = 'none';
    }
    return () => {
      if (confirmBtn) {
        confirmBtn.style.display = '';
      }
    };
  }, [confirmSelector]);

  const handleConfirm = useCallback(() => {
    return new Promise<void>((resolve, reject) => {
      const keyInput = document.querySelector(keySelector) as HTMLTextAreaElement | HTMLInputElement | null;
      if (!keyInput || !keyInput.value.trim()) {
        const globalAlert = (window as unknown as { showAlert?: (msg: string, bg: string, color: string, effect?: string) => void }).showAlert;
        if (typeof globalAlert === 'function') {
          globalAlert('Enter private key sent to your email-id.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
        }
        reject(new Error('Missing signing key'));
        return;
      }

      const onSuccess = () => {
        cleanup();
        resolve();
      };

      const onError = () => {
        cleanup();
        reject(new Error('Vote creation failed'));
      };

      const cleanup = () => {
        document.removeEventListener('ballotchain:vote-success', onSuccess);
        document.removeEventListener('ballotchain:vote-error', onError);
      };

      // Listen for the trusted voting.js completion events
      document.addEventListener('ballotchain:vote-success', onSuccess, { once: true });
      document.addEventListener('ballotchain:vote-error', onError, { once: true });

      // Trigger the existing trusted final-confirm button click
      const confirmBtn = document.querySelector(confirmSelector) as HTMLElement | null;
      if (confirmBtn) {
        confirmBtn.click();
      } else {
        cleanup();
        reject(new Error('Confirmation control missing'));
      }
    });
  }, [confirmSelector, keySelector]);

  return (
    <div
      className="slide-commit-island-wrapper flex flex-col items-center my-3"
      role="group"
      aria-label="Ballot Submission Slider"
    >
      <SlideCommit
        label="Slide to Cast Ballot"
        doneLabel="Ballot Recorded"
        errorLabel="Submission Failed"
        onConfirm={handleConfirm}
        width={300}
        height={52}
        radius={26}
        trackColor="#e5e7eb"
        handleColor="#4f46e5"
        successColor="#16a34a"
        dangerColor="#dc2626"
        holdMs={2000}
        disabled={disabled}
        className="shadow-sm"
      />
      <p className="text-[11px] text-gray-500 mt-2 text-center select-none" aria-hidden="true">
        Slide handle right or press Space / Enter on handle to confirm
      </p>
    </div>
  );
};

export default SlideCommitIsland;
