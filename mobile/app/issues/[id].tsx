import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { Eye, Share2, Sparkles } from 'lucide-react-native';
import React, { useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useServices } from '../../src/data/context';
import {
  useFixDates,
  useGallery,
  useIssue,
  useProposeFixDate,
  useSupport,
  useEscalation,
  useSupports,
  useVoteFixDate,
  useWithdrawSupport,
} from '../../src/data/queries';
import type { Status } from '../../src/domain/issue';
import { MAX_PHOTOS, categoryLabel, contributionsOpen, fullMoment, severityLabel, onTrack } from '../../src/domain/issue';
import { CategoryPlate } from '../../src/features/issues/CategoryPlate';
import { FixDatePoll } from '../../src/features/issues/FixDatePoll';
import { Gallery } from '../../src/features/issues/Gallery';
import { shareIssue } from '../../src/features/issues/share';
import { ConfirmationBar } from '../../src/features/issues/ConfirmationBar';
import { StatusChip } from '../../src/features/issues/StatusChip';
import { EscalationCard } from '../../src/features/issues/EscalationCard';
import { StatusTrack } from '../../src/features/issues/StatusTrack';
import { SupportComposer, SupportList } from '../../src/features/issues/Supports';
import { Avatar } from '../../src/features/profile/Avatar';
import { Centered, Notice } from '../../src/features/issues/NearbyFeed';
import { statusNote } from '../../src/domain/status';
import { metric, type as t, useTone } from '../../src/theme/tokens';

/**
 * The count is the control, the way an arrow beside a number always is. It is
 * the same gesture the feed card offers, so the reflex carries over instead of
 * dying on a page that only looked tappable.
 */
function Corroboration({
  count,
  supported,
  busy,
  onPress,
}: {
  count: number;
  supported: boolean;
  busy: boolean;
  onPress: () => void;
}) {
  const tone = useTone();
  return (
    <Pressable
      onPress={onPress}
      disabled={busy}
      style={[styles.corroboration, { opacity: busy ? 0.5 : 1 }]}>
      <View
        style={[
          styles.arrow,
          { backgroundColor: supported ? tone.accent : `${tone.accent}24` },
        ]}>
        <Eye size={20} color={supported ? '#000' : tone.accentDeep} />
      </View>
      <View style={{ marginLeft: 12, flex: 1 }}>
        <Text style={[t.display(22, '700'), { color: tone.ink }]}>{count}</Text>
        <Text style={[t.body(14), { color: tone.chalk, marginTop: 1 }]}>
          {supported
            ? count === 1
              ? 'you saw this — tap to withdraw'
              : `you and ${count - 1} other${count === 2 ? '' : 's'} saw this`
            : count === 1
              ? 'resident independently saw this'
              : 'residents independently saw this'}
        </Text>
      </View>
    </Pressable>
  );
}

/**
 * Marked as machine-written on purpose. It restates what people wrote, and a
 * reader deciding whether to trust a civic report should be able to tell that
 * line apart from the words a neighbour actually typed.
 */
function Summary({ text }: { text: string }) {
  const tone = useTone();
  return (
    <View style={[styles.summary, { backgroundColor: tone.surface }]}>
      <View style={styles.summaryHead}>
        <Sparkles size={13} color={tone.chalk} />
        <Text style={[t.body(13), { color: tone.chalk, marginLeft: 6 }]}>
          Summary of what people said
        </Text>
      </View>
      <Text style={[t.body(15), { color: tone.ink, marginTop: 8 }]}>{text}</Text>
    </View>
  );
}

export default function IssueDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const tone = useTone();
  const router = useRouter();
  const { auth, photos: camera } = useServices();
  const query = useIssue(id!);
  const gallery = useGallery(id!);
  const thread = useSupports(id!);
  const escalation = useEscalation(id!);
  const support = useSupport(id!);
  const withdraw = useWithdrawSupport(id!);
  const board = useFixDates(id!, query.data ? contributionsOpen(query.data) : false);
  const propose = useProposeFixDate(id!);
  const vote = useVoteFixDate(id!);
  const [attached, setAttached] = useState<string[]>([]);

  if (query.isPending) return <Centered><ActivityIndicator color={tone.accentDeep} /></Centered>;
  if (query.isError) return <Notice text={(query.error as Error).message} />;

  const issue = query.data;
  const critical = issue.severity === 'high';
  const mine = issue.reporter.id === auth.currentUserId();
  const supports = thread.data?.pages.flatMap((page) => page.items) ?? [];
  const images = gallery.data ?? issue.photos ?? [];

  const requireSignIn = () => {
    if (auth.currentUserId()) return false;
    router.push('/auth');
    return true;
  };

  const addPhoto = async () => {
    if (requireSignIn()) return;
    if (attached.length >= MAX_PHOTOS) return;
    try {
      const shots = await camera.captureMany(MAX_PHOTOS - attached.length);
      if (shots.length) {
        setAttached((prev) => [...prev, ...shots].slice(0, MAX_PHOTOS));
      }
    } catch (e) {
      Alert.alert('Could not add photo', (e as Error).message);
    }
  };

  const mySupport = supports.find((s) => s.mine);
  const threadTotal = thread.data?.pages[0]?.total ?? supports.length;

  const toggleSupport = () => {
    if (requireSignIn()) return;
    if (!issue.confirmed_by_me) {
      support.mutate(
        { body: '', photos: [] },
        { onError: (e) => Alert.alert('Could not confirm', (e as Error).message) },
      );
      return;
    }
    const drop = () =>
      withdraw.mutate(undefined, {
        onError: (e) => Alert.alert('Could not withdraw', (e as Error).message),
      });
    const carried = mySupport?.photos.length ?? 0;
    if (carried || mySupport?.body) {
      // Withdrawing deletes what came with the support, so it is not something
      // to do to somebody on a single tap without saying so.
      Alert.alert(
        'Withdraw your support?',
        carried
          ? `This also removes ${carried === 1 ? 'the photo' : `the ${carried} photos`} you added.`
          : 'This also removes what you wrote.',
        [
          { text: 'Keep it', style: 'cancel' },
          { text: 'Withdraw', style: 'destructive', onPress: drop },
        ],
      );
      return;
    }
    drop();
  };

  const submit = (body: string) => {
    if (requireSignIn()) return;
    support.mutate(
      { body, photos: attached },
      {
        onSuccess: () => setAttached([]),
        onError: (e) => Alert.alert('Could not post that', (e as Error).message),
      },
    );
  };

  return (
    <ScrollView contentContainerStyle={{ padding: metric.gutter, paddingBottom: 48 }}>
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable onPress={() => shareIssue(issue)} hitSlop={12}>
              <Share2 size={21} color={tone.ink} />
            </Pressable>
          ),
        }}
      />

      <View style={styles.row}>
        <Text style={[t.meta(13, '600', 0), { color: tone.ink }]}>
          {categoryLabel[issue.category]}
        </Text>
        <View style={[styles.dot, { backgroundColor: critical ? tone.hazard : tone.chalk }]} />
        <Text style={[t.meta(13, '600', 0), { color: critical ? tone.hazard : tone.chalk }]}>
          {severityLabel[issue.severity]}
        </Text>
      </View>
      <Text style={[t.body(13), { color: tone.chalk, marginTop: 3 }]}>
        {fullMoment(issue.created_at)}
      </Text>

      <Text style={[t.display(27, '700'), { color: tone.ink, marginTop: 10 }]}>{issue.title}</Text>
      <Text style={[t.body(16), { color: tone.chalk, marginTop: 10 }]}>{issue.description}</Text>

      <Pressable
        onPress={() => router.push(`/users/${issue.reporter.id}`)}
        style={styles.byline}
        hitSlop={6}>
        <Avatar id={issue.reporter.id} name={issue.reporter.display_name} size={26} />
        <Text style={[t.meta(12, '600', 0), { color: tone.ink, marginLeft: 8 }]}>
          {issue.reporter.display_name}
        </Text>
        <Text style={[t.meta(12, '500', 0), { color: tone.chalk, marginLeft: 6 }]}>
          reported this
        </Text>
      </Pressable>

      <View style={{ marginTop: 18 }}>
        {images.length ? (
          <Gallery photos={images} onAdd={addPhoto} />
        ) : (
          <CategoryPlate
            category={issue.category}
            severity={issue.severity}
            uri={issue.cover_url}
            height={230}
          />
        )}
      </View>

      {images.length > 1 && (
        <Text style={[t.body(13), { color: tone.chalk, marginTop: 10 }]}>
          {(() => {
            const people = new Set(images.map((p) => p.contributor.id)).size;
            return `${images.length} photos from ${people} ${people === 1 ? 'person' : 'people'}`;
          })()}
        </Text>
      )}

      {issue.ai_summary && <Summary text={issue.ai_summary} />}

      {onTrack(issue.status) && (
        <>
          <View style={[styles.divider, { backgroundColor: tone.hairline }]} />
          <Text style={[t.display(17, '700'), { color: tone.ink, marginBottom: 16 }]}>Progress</Text>

          <StatusChip status={issue.status} />
          <Text style={[t.body(14), { color: tone.chalk, marginTop: 10 }]}>
            {statusNote(issue.status)}
          </Text>

          <ConfirmationBar issue={issue} />
          <StatusTrack issue={issue} authority={escalation.data?.authority ?? null} />
          {escalation.data && <EscalationCard escalation={escalation.data} />}
          {contributionsOpen(issue) && board.data && (
            <FixDatePoll
              board={board.data}
              busy={propose.isPending || vote.isPending}
              signedIn={Boolean(auth.currentUserId())}
              onSignIn={() => router.push('/auth')}
              onPropose={(fixOn, fixTime) =>
                propose.mutate({ fixOn, fixTime }, {
                  onError: (e) => Alert.alert('Could not add that day', (e as Error).message),
                })
              }
              onVote={(row, on) =>
                vote.mutate(
                  { id: row.id, on },
                  { onError: (e) => Alert.alert('Could not update that', (e as Error).message) },
                )
              }
            />
          )}
        </>
      )}

      <View style={[styles.divider, { backgroundColor: tone.hairline }]} />
      <Corroboration
        count={issue.confirmation_count}
        supported={issue.confirmed_by_me}
        busy={support.isPending || withdraw.isPending}
        onPress={toggleSupport}
      />

      <View style={[styles.divider, { backgroundColor: tone.hairline }]} />
      <Text style={[t.display(17, '700'), { color: tone.ink }]}>
        {threadTotal === 1 ? '1 support' : `${threadTotal} supports`}
      </Text>
      <Text style={[t.body(13), { color: tone.chalk, marginTop: 3, marginBottom: 14 }]}>
        What people who went and looked have said.
      </Text>

      <SupportComposer
        busy={support.isPending || withdraw.isPending}
        supported={issue.confirmed_by_me}
        isReporter={mine}
        onSubmit={submit}
        onPickPhoto={addPhoto}
        attached={attached}
        onDropPhoto={(uri) => setAttached((prev) => prev.filter((u) => u !== uri))}
      />

      <SupportList
        supports={supports}
        loading={thread.isPending || thread.isFetchingNextPage}
        hasMore={Boolean(thread.hasNextPage)}
        onMore={() => thread.fetchNextPage()}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  byline: { flexDirection: 'row', alignItems: 'center', marginTop: 16 },
  dot: { width: 6, height: 6, borderRadius: 3, marginHorizontal: 8 },
  divider: { height: 1, marginVertical: 24 },
  corroboration: { flexDirection: 'row', alignItems: 'center' },
  arrow: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  summary: { marginTop: 18, padding: 14, borderRadius: metric.radius },
  summaryHead: { flexDirection: 'row', alignItems: 'center' },
});
