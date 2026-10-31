import React, { useState, useEffect, useCallback } from 'react';
import CodeSlots, { CodeSlotsStatus } from '../components/CodeSlots';

export interface OtpCodeSlotsIslandProps {
  length?: number;
  inputSelector?: string;
}

export const OtpCodeSlotsIsland: React.FC<OtpCodeSlotsIslandProps> = ({
  length = 6,
  inputSelector = '#otp-input'
}) => {
  const [value, setValue] = useState('');
  const [status, setStatus] = useState<CodeSlotsStatus>('idle');

  // Sync value back to the underlying Django input without logging or persistence
  const handleCodeChange = useCallback((newCode: string) => {
    setValue(newCode);
    const targetInput = document.querySelector(inputSelector) as HTMLInputElement | null;
    if (targetInput) {
      targetInput.value = newCode;
      targetInput.dispatchEvent(new Event('input', { bubbles: true }));
      targetInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }, [inputSelector]);

  const handleComplete = useCallback((completedCode: string) => {
    handleCodeChange(completedCode);
    const verifyBtn = document.getElementById('verify');
    if (verifyBtn) {
      verifyBtn.focus();
    }
  }, [handleCodeChange]);

  // Listen for verification error/reset events dispatched by candidate_details.js
  useEffect(() => {
    const handleOtpError = () => {
      setStatus('error');
      setTimeout(() => setStatus('idle'), 1800);
    };

    const handleOtpReset = () => {
      setValue('');
      setStatus('idle');
      const targetInput = document.querySelector(inputSelector) as HTMLInputElement | null;
      if (targetInput) {
        targetInput.value = '';
      }
    };

    document.addEventListener('ballotchain:otp-error', handleOtpError);
    document.addEventListener('ballotchain:otp-reset', handleOtpReset);

    // Hide fallback input visually while keeping it in the DOM for jQuery/form submission
    const targetInput = document.querySelector(inputSelector) as HTMLInputElement | null;
    if (targetInput) {
      targetInput.style.display = 'none';
    }

    return () => {
      document.removeEventListener('ballotchain:otp-error', handleOtpError);
      document.removeEventListener('ballotchain:otp-reset', handleOtpReset);
      if (targetInput) {
        targetInput.style.display = '';
      }
    };
  }, [inputSelector]);

  return (
    <div
      className="code-slots-wrapper flex flex-col items-center gap-1.5"
      role="group"
      aria-label="One-Time Passcode Verification"
    >
      <CodeSlots
        length={length}
        value={value}
        onChange={handleCodeChange}
        onComplete={handleComplete}
        status={status}
        slotSize={46}
        gap={8}
        radius={10}
        accentColor="#4f46e5"
        slotColor="#ffffff"
        digitColor="#1f2937"
        dangerColor="#ef4444"
        ariaLabel="Enter 6-digit OTP"
        className="shadow-sm"
      />
      {status === 'error' && (
        <span className="text-xs font-medium text-red-600 mt-1 animate-pulse" role="alert">
          Invalid OTP code. Please verify and re-enter.
        </span>
      )}
    </div>
  );
};

export default OtpCodeSlotsIsland;
