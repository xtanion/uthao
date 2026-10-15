import React from 'react';
import {
  Ban, BadgeCheck, CheckCheck, CircleAlert, CircleDot, ClipboardCheck, Copy,
  CircleX, Droplets, Flag, Footprints, Hourglass, LampCeiling, Landmark, MailCheck,
  RotateCcw, Send, TrafficCone, Trash2, TreeDeciduous, TriangleAlert, Wrench,
} from 'lucide-react-native';
import type { Category, Status } from '../../domain/issue';

const CATEGORY_ICON = {
  pothole_road: TriangleAlert,
  garbage: Trash2,
  footpath: Footprints,
  streetlight: LampCeiling,
  water_drainage: Droplets,
  manhole: CircleDot,
  traffic_infrastructure: TrafficCone,
  fallen_tree: TreeDeciduous,
  public_property: Landmark,
  other: CircleAlert,
} as const;

/**
 * One icon per status, chosen so the two "done" states cannot be mistaken for
 * each other: a claimed fix is paperwork (ClipboardCheck), a confirmed fix is
 * a second check (CheckCheck).
 */
const STATUS_ICON = {
  in_review: Hourglass,
  reported: Flag,
  community_verified: BadgeCheck,
  submitted_to_authority: Send,
  authority_acknowledged: MailCheck,
  in_progress: Wrench,
  resolution_claimed: ClipboardCheck,
  resolved: CheckCheck,
  reopened: RotateCcw,
  duplicate: Copy,
  removed: Ban,
  rejected: CircleX,
} as const satisfies Record<Status, unknown>;

export const CategoryGlyph = ({ category, ...rest }: { category: Category; size: number; color: string }) => {
  const Icon = CATEGORY_ICON[category];
  return <Icon {...rest} />;
};

export const StatusGlyph = ({ status, ...rest }: { status: Status; size: number; color: string }) => {
  const Icon = STATUS_ICON[status];
  return <Icon {...rest} />;
};
