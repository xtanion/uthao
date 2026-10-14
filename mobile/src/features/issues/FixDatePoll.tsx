import { useRouter } from 'expo-router';
import { Check, ChevronRight, Clock, Plus, Users, X } from 'lucide-react-native';
import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import type { FixDate, FixDates } from '../../domain/issue';
import { Avatar } from '../profile/Avatar';
import { metric, type as t, useTone } from '../../theme/tokens';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];
/** Far enough out to find a weekend, close enough to still mean something. */
const HORIZON = 28;
/** Hours people actually turn up to do this: before work, or after it. */
const TIMES = ['07:00', '08:00', '09:00', '10:00', '16:00', '17:00', '18:00'];
/** How many faces fit before the count does the talking. */
const FACES = 3;

const parts = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  const at = new Date(y, m - 1, d);
  return { weekday: WEEKDAYS[at.getDay()], day: d, month: MONTHS_SHORT[m - 1] };
};

const isoDay = (offset: number) => {
  const at = new Date();
  at.setDate(at.getDate() + offset);
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(
    at.getDate(),
  ).padStart(2, '0')}`;
};

const clockLabel = (value: string | null) => {
  if (!value) return null;
  const [h, m] = value.split(':').map(Number);
  const suffix = h < 12 ? 'am' : 'pm';
  const hour = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${hour} ${suffix}` : `${hour}:${String(m).padStart(2, '0')} ${suffix}`;
};

/**
 * When are people going to turn up.
 *
 * The authority has not moved, so the question stops being "will this get
 * fixed" and becomes "who is free on which day". That is a poll, but the thing
 * being counted is people committing their own Saturday, so turnout is shown
 * as faces and a headcount rather than a bar - it should read as a turnout,
 * not a score.
 */
export function FixDatePoll({
  board,
  busy,
  onPropose,
  onVote,
  onSignIn,
  signedIn,
}: {
  board: FixDates;
  busy: boolean;
  onPropose: (fixOn: string, fixTime: string | null) => void;
  onVote: (row: FixDate, on: boolean) => void;
  onSignIn: () => void;
  signedIn: boolean;
}) {
  const tone = useTone();
  const [picking, setPicking] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  const [showing, setShowing] = useState<FixDate | null>(null);

  const taken = useMemo(
    () => new Set(board.items.map((row) => row.fix_on)),
    [board.items],
  );
  const going = board.items.reduce((total, row) => total + row.vote_count, 0);
  const best = board.items.reduce<FixDate | null>(
    (top, row) => (top === null || row.vote_count > top.vote_count ? row : top),
    null,
  );

  const act = (run: () => void) => (signedIn ? run() : onSignIn());
  const close = () => {
    setPicking(false);
    setDay(null);
  };

  return (
    <View style={[styles.card, { borderColor: tone.hairline }]}>
      <View style={styles.head}>
        <Users size={15} color={tone.ink} />
        <Text style={[t.display(15, '700'), { color: tone.ink, marginLeft: 8, flex: 1 }]}>
          When can you fix it?
        </Text>
        {busy && <ActivityIndicator size="small" color={tone.accentDeep} />}
      </View>

      <Text style={[t.body(13), { color: tone.chalk, marginTop: 4 }]}>
        {board.items.length === 0
          ? 'Nobody has picked a day yet. Put one up and see who joins.'
          : best && best.vote_count > 1
            ? `${going} going. ${parts(best.fix_on).weekday} ${parts(best.fix_on).day} ${parts(best.fix_on).month} is ahead.`
            : `${going} going so far.`}
      </Text>

      {board.items.length > 0 && (
        <View style={[styles.rule, { backgroundColor: tone.hairline }]} />
      )}

      {board.items.map((row, i) => (
        <DayRow
          key={row.id}
          row={row}
          first={i === 0}
          busy={busy}
          onOpen={() => setShowing(row)}
          onToggle={() => act(() => onVote(row, !row.voted_by_me))}
        />
      ))}

      {picking ? (
        <View style={{ marginTop: 12 }}>
          <Text style={[t.body(13), { color: tone.chalk, marginBottom: 8 }]}>
            {day ? 'And roughly when?' : 'Pick the day you can be there.'}
          </Text>

          {day ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {TIMES.map((value) => (
                <Pressable
                  key={value}
                  disabled={busy}
                  onPress={() => {
                    close();
                    act(() => onPropose(day, value));
                  }}
                  style={[styles.timeChip, { backgroundColor: tone.bg }]}>
                  <Text style={[t.display(15, '600'), { color: tone.ink }]}>
                    {clockLabel(value)}
                  </Text>
                </Pressable>
              ))}
              <Pressable
                disabled={busy}
                onPress={() => {
                  close();
                  act(() => onPropose(day, null));
                }}
                style={[styles.timeChip, { backgroundColor: tone.bg }]}>
                <Text style={[t.body(14), { color: tone.chalk }]}>Decide later</Text>
              </Pressable>
            </ScrollView>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {Array.from({ length: HORIZON }, (_, i) => isoDay(i)).map((iso) => {
                const { weekday, day: dayOfMonth, month } = parts(iso);
                const already = taken.has(iso);
                return (
                  <Pressable
                    key={iso}
                    disabled={busy}
                    // A day already up needs no hour; backing it is agreeing
                    // to the one whoever proposed it set.
                    onPress={() =>
                      already ? (close(), act(() => onPropose(iso, null))) : setDay(iso)
                    }
                    style={[
                      styles.chip,
                      { backgroundColor: already ? `${tone.accent}22` : tone.bg },
                    ]}>
                    <Text style={[t.meta(10, '600', 0.4), { color: tone.chalk }]}>
                      {weekday}
                    </Text>
                    <Text style={[t.display(17, '700'), { color: tone.ink, marginTop: 2 }]}>
                      {dayOfMonth}
                    </Text>
                    <Text style={[t.meta(10, '500', 0.4), { color: tone.chalk }]}>
                      {month}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          )}

          <Pressable onPress={close} hitSlop={8} style={styles.cancel}>
            <Text style={[t.body(13), { color: tone.chalk }]}>Cancel</Text>
          </Pressable>
        </View>
      ) : (
        <Pressable
          disabled={busy || (board.proposed_by_me && board.remaining_slots === 0)}
          onPress={() => act(() => setPicking(true))}
          style={[
            styles.add,
            {
              backgroundColor: `${tone.accent}1f`,
              opacity: board.proposed_by_me && board.remaining_slots === 0 ? 0.5 : 1,
            },
          ]}>
          <View style={[styles.addMark, { backgroundColor: tone.accent }]}>
            <Plus size={15} color="#000" strokeWidth={2.6} />
          </View>
          <Text style={[t.display(15, '600'), { color: tone.accentDeep, marginLeft: 9 }]}>
            {board.proposed_by_me ? 'Offer another day' : 'Offer a day you can be there'}
          </Text>
        </Pressable>
      )}

      <Text style={[t.body(12), { color: tone.chalk, marginTop: 10 }]}>
        {board.proposed_by_me
          ? 'You have put a day forward. You can still back any of the others.'
          : board.remaining_slots === 0
            ? 'All five days are taken. Back one of them.'
            : `One day each, ${board.remaining_slots} ${board.remaining_slots === 1 ? 'slot' : 'slots'} left.`}
      </Text>

      <GoingSheet row={showing} onClose={() => setShowing(null)} />
    </View>
  );
}

function DayRow({
  row,
  first,
  busy,
  onOpen,
  onToggle,
}: {
  row: FixDate;
  first: boolean;
  busy: boolean;
  onOpen: () => void;
  onToggle: () => void;
}) {
  const tone = useTone();
  const { weekday, day, month } = parts(row.fix_on);
  const clock = clockLabel(row.fix_time);
  const extra = row.vote_count - Math.min(row.going.length, FACES);

  return (
    <Pressable
      disabled={busy}
      onPress={onOpen}
      style={[
        styles.day,
        { borderTopColor: tone.hairline, borderTopWidth: first ? 0 : 1 },
      ]}>
      <View style={styles.date}>
        <Text style={[t.meta(10, '600', 0.4), { color: tone.chalk }]}>{weekday}</Text>
        <Text style={[t.display(19, '700'), { color: tone.ink }]}>{day}</Text>
        <Text style={[t.meta(10, '500', 0.4), { color: tone.chalk }]}>{month}</Text>
      </View>

      <View style={{ flex: 1, marginLeft: 12 }}>
        <View style={styles.row}>
          <Clock size={13} color={clock ? tone.ink : tone.chalk} />
          <Text
            style={[
              t.display(14, '600'),
              { color: clock ? tone.ink : tone.chalk, marginLeft: 5 },
            ]}>
            {clock ?? 'Time to be decided'}
          </Text>
        </View>

        <View style={[styles.row, { marginTop: 6 }]}>
          <View style={styles.stack}>
            {row.going.slice(0, FACES).map((person, i) => (
              <View key={person.id} style={{ marginLeft: i === 0 ? 0 : -7 }}>
                <Avatar id={person.id} name={person.display_name} size={20} />
              </View>
            ))}
          </View>
          <Text style={[t.body(12.5), { color: tone.chalk, marginLeft: 7 }]}>
            {extra > 0 ? `+${extra} more · ` : ''}
            {row.vote_count === 1 ? '1 going' : `${row.vote_count} going`}
          </Text>
          <ChevronRight size={14} color={tone.chalk} />
        </View>
      </View>

      <Pressable
        disabled={busy}
        onPress={onToggle}
        hitSlop={10}
        accessibilityLabel={row.voted_by_me ? 'You are going' : 'Say you will be there'}
        style={[
          styles.tick,
          row.voted_by_me
            ? { backgroundColor: tone.accent }
            : { backgroundColor: tone.surface },
        ]}>
        {row.voted_by_me && <Check size={14} color="#000" strokeWidth={3} />}
      </Pressable>
    </Pressable>
  );
}

/** Who is turning up, by name. The count answers how many; this answers who. */
function GoingSheet({ row, onClose }: { row: FixDate | null; onClose: () => void }) {
  const tone = useTone();
  const router = useRouter();
  if (!row) return null;
  const { weekday, day, month } = parts(row.fix_on);
  const clock = clockLabel(row.fix_time);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { backgroundColor: tone.bg }]}>
        <View style={styles.grabber}>
          <View style={[styles.grabberBar, { backgroundColor: tone.hairline }]} />
        </View>

        <View style={styles.sheetHead}>
          <Text style={[t.display(20, '700'), { color: tone.ink }]}>
            {weekday} {day} {month}
            {clock ? `, ${clock}` : ''}
          </Text>
          <Text style={[t.body(14), { color: tone.chalk, marginTop: 4 }]}>
            {row.vote_count === 1
              ? '1 person is going.'
              : `${row.vote_count} people are going.`}
            {row.mine ? (
              ' You put this day up.'
            ) : (
              <>
                {' '}
                <Text
                  suppressHighlighting
                  onPress={() => {
                    onClose();
                    router.push(`/users/${row.proposed_by.id}`);
                  }}
                  style={{ color: tone.ink, fontWeight: '600' }}>
                  {row.proposed_by.display_name}
                </Text>
                {' put it up.'}
              </>
            )}
          </Text>
        </View>

        <ScrollView style={{ flexGrow: 0 }}>
          {row.going.map((person) => (
            <Pressable
              key={person.id}
              onPress={() => {
                onClose();
                router.push(`/users/${person.id}`);
              }}
              style={styles.person}>
              <Avatar id={person.id} name={person.display_name} size={36} />
              <Text style={[t.display(15, '600'), { color: tone.ink, marginLeft: 12, flex: 1 }]}>
                {person.display_name}
              </Text>
              {person.id === row.proposed_by.id && (
                <Text style={[t.body(12.5), { color: tone.chalk }]}>put this up</Text>
              )}
            </Pressable>
          ))}
          {row.vote_count > row.going.length && (
            <Text style={[t.body(13), { color: tone.chalk, padding: metric.gutter }]}>
              and {row.vote_count - row.going.length} more.
            </Text>
          )}
        </ScrollView>

        <Pressable onPress={onClose} style={[styles.done, { backgroundColor: tone.surface }]}>
          <X size={16} color={tone.ink} />
          <Text style={[t.display(15, '600'), { color: tone.ink, marginLeft: 7 }]}>
            Close
          </Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: metric.radius, padding: 14, marginTop: 14 },
  head: { flexDirection: 'row', alignItems: 'center' },
  row: { flexDirection: 'row', alignItems: 'center' },
  day: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12 },
  date: { width: 44, alignItems: 'center' },
  stack: { flexDirection: 'row', alignItems: 'center' },
  tick: {
    width: 28, height: 28, borderRadius: 14,
    alignItems: 'center', justifyContent: 'center', marginLeft: 8,
  },
  chip: { width: 54, alignItems: 'center', paddingVertical: 9, marginRight: 8, borderRadius: 10 },
  timeChip: {
    paddingHorizontal: 14, paddingVertical: 11, marginRight: 8, borderRadius: 10,
    alignItems: 'center', justifyContent: 'center',
  },
  rule: { height: 1, marginTop: 12 },
  add: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    borderRadius: 999, paddingVertical: 12, marginTop: 14,
  },
  addMark: {
    width: 24, height: 24, borderRadius: 12,
    alignItems: 'center', justifyContent: 'center',
  },
  cancel: { alignSelf: 'center', paddingVertical: 10 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    maxHeight: '76%', paddingBottom: 26,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
  },
  grabber: { alignItems: 'center', paddingTop: 8, paddingBottom: 4 },
  grabberBar: { width: 36, height: 4, borderRadius: 2 },
  sheetHead: { paddingHorizontal: metric.gutter, paddingTop: 10, paddingBottom: 14 },
  person: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: metric.gutter, paddingVertical: 10,
  },
  done: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    marginHorizontal: metric.gutter, marginTop: 14, height: 48, borderRadius: 999,
  },
});
