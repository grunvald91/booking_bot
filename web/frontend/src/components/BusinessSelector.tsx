import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Check } from 'lucide-react';
import type { Business } from '../api/client';

interface Props {
  businesses: Business[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

/**
 * Компактный dropdown выбора бизнеса для шапки (headerExtra в AdminShell).
 * Триггер — узкая пилюля с текущим названием (обрезается многоточием),
 * список остальных бизнесов открывается ниже поверх контента.
 */
export function BusinessSelector({ businesses, selectedId, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [open]);

  if (businesses.length <= 1) return null;

  const current = businesses.find((b) => b.id === selectedId);

  return (
    <div ref={ref} style={{ position: 'relative', flexShrink: 0, maxWidth: '42%' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="ds-chip"
        style={{ maxWidth: '100%', overflow: 'hidden' }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {current?.name ?? 'Бизнес'}
        </span>
        <ChevronDown
          size={14}
          style={{ flexShrink: 0, transition: 'transform 0.15s ease', transform: open ? 'rotate(180deg)' : 'none' }}
        />
      </button>

      {open && (
        <div
          className="ds-card"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            zIndex: 95,
            minWidth: 200,
            maxWidth: 'min(80vw, 280px)',
            padding: 6,
            boxShadow: 'var(--sh-pop)',
            maxHeight: '60vh',
            overflowY: 'auto',
          }}
        >
          {businesses.map((b) => {
            const active = b.id === selectedId;
            return (
              <button
                key={b.id}
                onClick={() => {
                  onSelect(b.id);
                  setOpen(false);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                  width: '100%',
                  textAlign: 'left',
                  padding: '9px 10px',
                  borderRadius: 9,
                  border: 'none',
                  background: active ? 'var(--s-accent-soft)' : 'transparent',
                  color: active ? 'var(--s-accent)' : 'var(--s-text)',
                  fontSize: 14,
                  fontWeight: active ? 700 : 500,
                  fontFamily: 'inherit',
                  cursor: 'pointer',
                }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.name}</span>
                {active && <Check size={15} style={{ flexShrink: 0 }} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
