import type { Category, Severity, Status } from './issue';
import { categoryLabel, statusLabel } from './issue';

export const ACTIVITY_TYPES = [
  'support_received',
  'authority_replied',
  'status_changed',
  'support_rejected',
] as const;
export type ActivityType = (typeof ACTIVITY_TYPES)[number];

/** Just enough of an issue to render a notification row. */
export type IssueSummary = {
  id: string;
  title: string;
  category: Category;
  severity: Severity;
  status: Status;
  cover_url: string | null;
  confirmation_count: number;
};

export type Notification = {
  id: string;
  type: ActivityType;
  read: boolean;
  actor_name: string | null;
  from_status: Status | null;
  to_status: Status | null;
  /** Why: on support_rejected, the reason the support was taken down. */
  note?: string | null;
  issue: IssueSummary;
  created_at: string;
};

export type NotificationPage = {
  items: Notification[];
  next_cursor: string | null;
  unread_count: number;
};

/**
 * The row's own sentence. Confirmations name the person, because knowing a
 * neighbour backed you up is the point; a status change names no one, because
 * the crowd moved it rather than any one person.
 */
export const notificationLine = (item: Notification): string => {
  if (item.type === 'support_received') {
    const who = item.actor_name ?? 'Someone';
    return `${who} independently saw this`;
  }
  if (item.type === 'support_rejected') {
    return `Your support wasn't added. ${item.note ?? ''}`.trim();
  }
  if (item.type === 'authority_replied') {
    return 'The authority replied to your report';
  }
  if (item.to_status === 'community_verified') {
    return 'Enough neighbours confirmed this to verify it';
  }
  return `Status moved to ${statusLabel(item.to_status ?? item.issue.status)}`;
};

export const notificationContext = (item: Notification): string =>
  item.issue.title.trim() || categoryLabel[item.issue.category];
