/** The tallies behind the score, each one separately legible. */
export type Contributions = {
  posts: number;
  upvotes_received: number;
  supports_given: number;
  comments_written: number;
  resolutions: number;
};

/** What /me returns: identity only, no tallies. */
export type Account = {
  id: string;
  display_name: string;
  avatar_url: string | null;
};

export type Profile = {
  id: string;
  display_name: string;
  avatar_url: string | null;
  reputation: number;
  contributions: Contributions;
  joined_at: string;
};

export const CONTRIBUTION_LABELS: Record<keyof Contributions, string> = {
  posts: 'Reports',
  upvotes_received: 'Confirmations received',
  supports_given: 'Reports supported',
  comments_written: 'Comments',
  resolutions: 'Resolved',
};

/** Mirrors the server's weights. Shown so the score is never a black box. */
export const REPUTATION_WEIGHTS = { upvote: 1, post: 2, resolution: 5 } as const;

/** A plain-language tier for the score, so a number has a name to grow into. */
export const standing = (reputation: number): string => {
  if (reputation >= 200) return 'Local hero';
  if (reputation >= 50) return 'Trusted neighbour';
  if (reputation >= 10) return 'Regular';
  return 'New member';
};

export const initials = (name: string): string => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

export const joinedLabel = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
};
