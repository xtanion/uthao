import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import {
  ApiIssuesRepository,
  ApiNotificationsRepository,
  ApiUsersRepository,
} from './apiRepository';
import {
  FakeAuthGateway,
  FakeIssuesRepository,
  FakeNotificationsRepository,
  FakeUsersRepository,
  FixedLocationService,
  StubPhotoSource,
} from './fakeIssues';
import type {
  AuthGateway,
  IssuesRepository,
  LocationService,
  NotificationsRepository,
  PhotoSource,
  UsersRepository,
} from './repository';
import { ApiAuthGateway, CameraPhotoSource, DeviceLocationService } from './services';

export type Services = {
  issues: IssuesRepository;
  notifications: NotificationsRepository;
  users: UsersRepository;
  auth: AuthGateway;
  location: LocationService;
  photos: PhotoSource;
};

/** Demo mode runs the whole app on in-memory data: no API, no SMS, no camera. */
export const DEMO = process.env.EXPO_PUBLIC_DEMO === 'true';

export const demoServices = (over: Partial<Services> = {}): Services => {
  const auth = over.auth ?? new FakeAuthGateway();
  const issues = over.issues ?? new FakeIssuesRepository(undefined, auth);
  return {
    auth,
    issues,
    users:
      over.users ??
      (issues instanceof FakeIssuesRepository
        ? new FakeUsersRepository(issues)
        : new FakeUsersRepository(new FakeIssuesRepository(undefined, auth))),
    notifications: over.notifications ?? new FakeNotificationsRepository(),
    location: over.location ?? new FixedLocationService(),
    photos: over.photos ?? new StubPhotoSource(),
  };
};

export const liveServices = (): Services => ({
  issues: new ApiIssuesRepository(),
  notifications: new ApiNotificationsRepository(),
  users: new ApiUsersRepository(),
  auth: new ApiAuthGateway(),
  location: new DeviceLocationService(),
  // Evidence has to be taken in the moment, so the library is never an option
  // in a real build. __DEV__ is what makes that a guarantee rather than a
  // default: a release bundle cannot reach the picker whatever the env says,
  // while a simulator with no camera can still be worked on.
  photos: new CameraPhotoSource(
    __DEV__ && process.env.EXPO_PUBLIC_PHOTO_SOURCE === 'library' ? 'library' : 'camera',
  ),
});

const ServicesContext = createContext<Services | null>(null);

export function ServicesProvider({
  children,
  value,
}: {
  children: React.ReactNode;
  value?: Services;
}) {
  const services = useMemo(() => value ?? (DEMO ? demoServices() : liveServices()), [value]);
  // Nothing renders until the stored session is back, so no screen reads the
  // signed-in user as null and sends a returning user to sign in again.
  const [restored, setRestored] = useState(!services.auth.restore);

  useEffect(() => {
    if (restored) return;
    let live = true;
    services.auth
      .restore?.()
      .catch(() => undefined)
      .finally(() => live && setRestored(true));
    return () => {
      live = false;
    };
  }, [services, restored]);

  if (!restored) return null;
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

export function useServices(): Services {
  const services = useContext(ServicesContext);
  if (!services) throw new Error('useServices must be used inside ServicesProvider');
  return services;
}
