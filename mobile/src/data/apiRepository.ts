import { File } from 'expo-file-system';
import type {
  Category,
  Duplicate,
  FixDates,
  GeoPoint,
  Issue,
  NewIssue,
  Photo,
  SupportDraft,
  SupportPage,
  Status,
} from '../domain/issue';
import type { NotificationPage } from '../domain/notification';
import type { Escalation } from '../domain/escalation';
import type { Account, Profile } from '../domain/profile';
import { request } from './client';
import { ApiError } from './repository';
import type {
  IssuesRepository,
  NearbyQuery,
  NotificationsRepository,
  Page,
  UsersRepository,
} from './repository';
import { DUPLICATE_RADIUS_M, PAGE_SIZE } from './repository';

/** Expo installs expo/fetch as the global fetch, and it reads the bytes of a
 *  File but refuses React Native's { uri, name, type } parts outright. */
const photoPart = (uri: string) => new File(uri);

const appendPhotos = (form: FormData, uris: string[]) => {
  uris.forEach((uri) => form.append('photos', photoPart(uri)));
};

export class ApiIssuesRepository implements IssuesRepository {
  nearby({
    point,
    radiusM = 500,
    category,
    severity,
    status,
    q,
    cursor,
    limit = PAGE_SIZE,
  }: NearbyQuery) {
    return request<Page>('/issues/nearby', {
      query: {
        lat: point.latitude,
        lng: point.longitude,
        radius_m: radiusM,
        category,
        severity,
        status,
        q: q?.trim() || undefined,
        cursor,
        limit,
      },
    });
  }

  async escalation(id: string) {
    // 404 here means "not raised yet", which is a state rather than a failure.
    try {
      return await request<Escalation>(`/issues/${id}/escalation`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }

  mine(cursor?: string | null) {
    return request<Page>('/me/issues', { query: { cursor, limit: PAGE_SIZE } });
  }

  get(id: string) {
    return request<Issue>(`/issues/${id}`);
  }

  confirm(id: string) {
    return request<Issue>(`/issues/${id}/confirmations`, { method: 'POST' });
  }

  unconfirm(id: string) {
    return request<Issue>(`/issues/${id}/confirmations`, { method: 'DELETE' });
  }

  async duplicates(point: GeoPoint, category: Category) {
    const page = await request<{ items: Duplicate[] }>('/issues/duplicates', {
      query: {
        lat: point.latitude,
        lng: point.longitude,
        category,
        radius_m: DUPLICATE_RADIUS_M,
      },
    });
    return page.items;
  }

  support(id: string, draft: SupportDraft) {
    const form = new FormData();
    // Always sent, even empty: it is what makes the request a form.
    form.append('body', draft.body ?? '');
    appendPhotos(form, draft.photos);
    if (draft.location) {
      form.append('latitude', String(draft.location.latitude));
      form.append('longitude', String(draft.location.longitude));
    }
    return request<Issue>(`/issues/${id}/supports`, { method: 'POST', body: form });
  }

  withdrawSupport(id: string) {
    return request<Issue>(`/issues/${id}/supports`, { method: 'DELETE' });
  }

  supports(id: string, cursor?: string | null) {
    return request<SupportPage>(`/issues/${id}/supports`, {
      query: { cursor, limit: PAGE_SIZE },
    });
  }

  photos(id: string) {
    return request<Photo[]>(`/issues/${id}/photos`);
  }

  fixDates(id: string) {
    return request<FixDates>(`/issues/${id}/fix-dates`);
  }

  proposeFixDate(id: string, fixOn: string, fixTime?: string | null) {
    return request<FixDates>(`/issues/${id}/fix-dates`, {
      method: 'POST',
      body: JSON.stringify({ fix_on: fixOn, fix_time: fixTime ?? null }),
    });
  }

  voteFixDate(id: string, fixDateId: string, on: boolean) {
    return request<FixDates>(`/issues/${id}/fix-dates/${fixDateId}/votes`, {
      method: on ? 'POST' : 'DELETE',
    });
  }

  create(draft: NewIssue) {
    const form = new FormData();
    form.append('client_report_id', draft.client_report_id);
    form.append('title', draft.title);
    form.append('description', draft.description);
    form.append('category', draft.category);
    form.append('severity', draft.severity);
    form.append('latitude', String(draft.latitude));
    form.append('longitude', String(draft.longitude));
    appendPhotos(form, draft.photos);
    return request<Issue>('/issues', { method: 'POST', body: form });
  }
}

export class ApiNotificationsRepository implements NotificationsRepository {
  list(cursor?: string | null) {
    return request<NotificationPage>('/notifications', {
      query: { cursor, limit: PAGE_SIZE },
    });
  }

  async markRead(ids?: string[]) {
    const result = await request<{ unread_count: number }>('/notifications/read', {
      method: 'POST',
      body: JSON.stringify(ids ? { ids } : {}),
    });
    return result.unread_count;
  }
}

export class ApiUsersRepository implements UsersRepository {
  profile(userId: string) {
    return request<Profile>(`/users/${userId}`);
  }

  issues(userId: string, cursor?: string | null, status?: Status) {
    return request<Page>(`/users/${userId}/issues`, {
      query: { cursor, limit: PAGE_SIZE, status },
    });
  }

  supports(userId: string, cursor?: string | null) {
    return request<Page>(`/users/${userId}/supports`, {
      query: { cursor, limit: PAGE_SIZE },
    });
  }

  updateName(displayName: string) {
    return request<Account>('/me', {
      method: 'PATCH',
      body: JSON.stringify({ display_name: displayName }),
    });
  }

  setAvatar(uri: string) {
    const form = new FormData();
    form.append('photo', photoPart(uri));
    return request<Account>('/me/avatar', { method: 'PUT', body: form });
  }

  clearAvatar() {
    return request<Account>('/me/avatar', { method: 'DELETE' });
  }
}
