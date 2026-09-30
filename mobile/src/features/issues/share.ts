import { Share } from 'react-native';
import type { Issue } from '../../domain/issue';
import { categoryLabel, fullMoment, statusLabel } from '../../domain/issue';

/**
 * Opens the system share sheet.
 *
 * Wording is provisional and deliberately kept in one place. What a shared
 * report should say is a decision about who it is for — a neighbour, a
 * councillor, a newsroom — and that has not been made yet.
 */
export async function shareIssue(issue: Issue) {
  const where = issue.locality ? ` in ${issue.locality}` : '';
  const backing =
    issue.confirmation_count > 0
      ? `\n${issue.confirmation_count} ${issue.confirmation_count === 1 ? 'hooman has' : 'hoomans have'} independently confirmed it.`
      : '';

  const message = [
    issue.title,
    '',
    `${categoryLabel[issue.category]}${where} · ${statusLabel(issue.status)}`,
    `Reported ${fullMoment(issue.created_at)}.${backing}`,
    '',
    `fihy://issues/${issue.id}`,
  ].join('\n');

  try {
    await Share.share({ title: issue.title, message });
  } catch {
    // The sheet was dismissed, or the platform refused it. Neither is worth
    // interrupting the reader over.
  }
}
