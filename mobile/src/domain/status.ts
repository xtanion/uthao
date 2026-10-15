import type { Status } from './issue';

/**
 * How a status should read. Five tones, each its own colour so a card says
 * where a report stands without a label: amber waiting, blue moving, green
 * done, red back again. Hazard red is still reserved for something wrong.
 */
export type StatusTone =
  | 'neutral'   // filed, nothing owed yet
  | 'progress'  // somebody is acting on it
  | 'good'      // corroborated or fixed
  | 'warn'      // needs attention again
  | 'muted';    // no longer a live report

export type StatusMeta = {
  /** Short enough for a feed card. */
  label: string;
  tone: StatusTone;
  /** One line for the detail screen: what this state actually means. */
  note: string;
};

/**
 * The single definition of the report lifecycle. Labels were derived from the
 * enum before, which produced "Submitted To Authority" and told a reader
 * nothing they did not already know from the field name.
 */
export const STATUS_META: Record<Status, StatusMeta> = {
  in_review: {
    label: 'In review',
    tone: 'neutral',
    note: 'Checking your photos. It goes live for people nearby once that is done, usually within a minute.',
  },
  reported: {
    label: 'Reported',
    tone: 'neutral',
    note: 'Filed, and waiting for someone else to photograph it too.',
  },
  community_verified: {
    label: 'Confirmed',
    tone: 'good',
    note: 'Enough neighbours photographed this independently for it to count as corroborated.',
  },
  submitted_to_authority: {
    label: 'Raised',
    tone: 'progress',
    note: 'Sent to the body responsible for it, with the photographs attached.',
  },
  authority_acknowledged: {
    label: 'Acknowledged',
    tone: 'progress',
    note: 'The authority has replied to confirm they received it.',
  },
  in_progress: {
    label: 'Work started',
    tone: 'progress',
    note: 'The authority says the work is under way.',
  },
  resolution_claimed: {
    label: 'Fix claimed',
    tone: 'progress',
    note: 'Said to be fixed. Nobody here has been back to check yet.',
  },
  resolved: {
    label: 'Fixed',
    tone: 'good',
    note: 'Fixed, and nobody has reported it back since.',
  },
  reopened: {
    label: 'Reopened',
    tone: 'warn',
    note: 'It came back after a fix was claimed, so it is a live report again.',
  },
  duplicate: {
    label: 'Duplicate',
    tone: 'muted',
    note: 'The same problem as another report, which carries the evidence instead.',
  },
  removed: {
    label: 'Removed',
    tone: 'muted',
    note: 'Taken down, so it no longer appears to anyone else.',
  },
  rejected: {
    label: 'Not published',
    tone: 'warn',
    note: "The photos didn't pass the check, so only you can see this.",
  },
};

export const statusNote = (status: Status): string => STATUS_META[status].note;
export const statusTone = (status: Status): StatusTone => STATUS_META[status].tone;
