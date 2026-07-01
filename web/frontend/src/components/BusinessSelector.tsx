import type { Business } from '../api/client';

interface Props {
  businesses: Business[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  vertical?: boolean;
}

export function BusinessSelector({ businesses, selectedId, onSelect, vertical }: Props) {
  if (businesses.length <= 1) return null;

  if (vertical) {
    return (
      <div className="flex flex-col gap-1.5 mb-3">
        {businesses.map((b) => (
          <button
            key={b.id}
            onClick={() => onSelect(b.id)}
            className={`w-full text-left px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
              selectedId === b.id
                ? 'bg-apple-blue text-white shadow-sm'
                : 'bg-apple-bg text-apple-gray hover:bg-gray-200'
            }`}
          >
            {b.name}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto scrollbar-hide" style={{ flexShrink: 1, minWidth: 0, maxWidth: '45%' }}>
      <div className="flex gap-1 bg-apple-bg rounded-full p-0.5 w-fit">
        {businesses.map((b) => (
          <button
            key={b.id}
            onClick={() => onSelect(b.id)}
            className={`px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap transition-all ${
              selectedId === b.id
                ? 'bg-white text-apple-text shadow-sm'
                : 'text-apple-gray'
            }`}
          >
            {b.name}
          </button>
        ))}
      </div>
    </div>
  );
}
