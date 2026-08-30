import { useRouter } from 'expo-router';
import { Search, X } from 'lucide-react-native';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Animated,
  ActivityIndicator,
  FlatList,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useServices } from '../../data/context';
import { useConfirm, useSearch, type SearchFilters } from '../../data/queries';
import { SEARCH_RADIUS_M } from '../../data/repository';
import type { Category, GeoPoint, Issue, Severity } from '../../domain/issue';
import { CATEGORIES, SEVERITIES, categoryLabel, severityLabel } from '../../domain/issue';
import { metric, type as t, useTone } from '../../theme/tokens';
import { CategoryGlyph } from '../issues/glyphs';
import { IssueCard } from '../issues/IssueCard';
import { Centered, Notice } from '../issues/NearbyFeed';
import { useChrome, useChromeOnScroll } from '../shell/chrome';

const RANGE_KM = SEARCH_RADIUS_M / 1000;

/** Keystrokes are cheap; round trips are not. */

/** Native-driven onScroll needs an explicitly animated list. */
const ScrollList = Animated.createAnimatedComponent(
  FlatList,
) as unknown as typeof FlatList;

function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

export function SearchScreen({ point }: { point: GeoPoint }) {
  const tone = useTone();
  const router = useRouter();
  const { auth } = useServices();
  const confirm = useConfirm();
  const chrome = useChromeOnScroll();
  const { insets } = useChrome();

  const [text, setText] = useState('');
  const [category, setCategory] = useState<Category | undefined>();
  const [severity, setSeverity] = useState<Severity | undefined>();

  const filters: SearchFilters = { q: useDebounced(text), category, severity };
  const active = filters.q.length > 0 || Boolean(category) || Boolean(severity);
  const results = useSearch(point, filters);

  const issues = useMemo(
    () => results.data?.pages.flatMap((p) => p.items) ?? [],
    [results.data],
  );

  const onConfirm = useCallback(
    (issue: Issue) => {
      if (!auth.currentUserId()) {
        router.push('/auth');
        return;
      }
      confirm.mutate({ id: issue.id, confirmed: issue.confirmed_by_me });
    },
    [auth, confirm, router],
  );

  return (
    <View style={{ flex: 1, paddingTop: insets.top }}>
      <View style={styles.fieldRow}>
        <View style={[styles.field, { backgroundColor: tone.surface, borderColor: tone.hairline }]}>
          <Search size={17} color={text ? tone.ink : tone.chalk} />
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder={`Search reports within ${RANGE_KM} km`}
            placeholderTextColor={tone.chalk}
            autoCorrect={false}
            returnKeyType="search"
            style={[t.body(16), styles.input, { color: tone.ink }]}
          />
          {text.length > 0 && (
            <Pressable onPress={() => setText('')} hitSlop={10}>
              <X size={17} color={tone.chalk} />
            </Pressable>
          )}
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        style={styles.stripBar}
        contentContainerStyle={styles.strip}>
        {SEVERITIES.map((value) => (
          <Chip
            key={value}
            label={severityLabel[value]}
            selected={severity === value}
            hazard={value === 'high'}
            onPress={() => setSeverity(severity === value ? undefined : value)}
          />
        ))}
        <View style={[styles.stripDivider, { backgroundColor: tone.hairline }]} />
        {CATEGORIES.map((value) => (
          <Chip
            key={value}
            label={categoryLabel[value]}
            selected={category === value}
            glyph={value}
            onPress={() => setCategory(category === value ? undefined : value)}
          />
        ))}
      </ScrollView>

      {!active ? (
        <Notice
          text={`Search titles and descriptions of reports within ${RANGE_KM} km, or narrow by severity and category.`}
        />
      ) : results.isPending ? (
        <Centered>
          <ActivityIndicator color={tone.accentDeep} />
        </Centered>
      ) : results.isError ? (
        <Notice text={(results.error as Error).message} />
      ) : !issues.length ? (
        <Notice
          text={
            filters.q
              ? `Nothing matches “${filters.q}” within ${RANGE_KM} km.`
              : `Nothing within ${RANGE_KM} km matches those filters.`
          }
        />
      ) : (
        <ScrollList
          data={issues}
          keyExtractor={(issue) => issue.id}
          {...chrome}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          contentContainerStyle={{ paddingBottom: insets.bottom + 96 }}
          ListHeaderComponent={
            <Text style={[t.meta(11, '600', 0), styles.count, { color: tone.chalk }]}>
              {issues.length}
              {results.hasNextPage ? '+' : ''} {issues.length === 1 ? 'result' : 'results'}
            </Text>
          }
          onEndReachedThreshold={0.6}
          onEndReached={() =>
            results.hasNextPage && !results.isFetchingNextPage && results.fetchNextPage()
          }
          ListFooterComponent={
            results.isFetchingNextPage ? (
              <View style={{ paddingVertical: 26 }}>
                <ActivityIndicator color={tone.accentDeep} />
              </View>
            ) : null
          }
          renderItem={({ item }) => (
            <IssueCard
              issue={item}
              onPress={() => router.push(`/issues/${item.id}`)}
              onConfirm={() => onConfirm(item)}
            />
          )}
        />
      )}
    </View>
  );
}

function Chip({
  label,
  selected,
  onPress,
  glyph,
  hazard = false,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  glyph?: Category;
  hazard?: boolean;
}) {
  const tone = useTone();
  const ink = selected ? '#000' : hazard ? tone.hazard : tone.ink;
  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.chip,
        selected
          ? { backgroundColor: tone.accent, borderColor: tone.accent }
          : { backgroundColor: 'transparent', borderColor: tone.hairline },
      ]}>
      {glyph && <CategoryGlyph category={glyph} size={14} color={ink} />}
      <Text style={[t.meta(12, '600', 0), { color: ink, marginLeft: glyph ? 5 : 0 }]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fieldRow: { paddingHorizontal: metric.gutter, paddingTop: 10 },
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 44,
    borderRadius: 999,
    borderWidth: 1,
    paddingHorizontal: 14,
  },
  input: { flex: 1, marginLeft: 9, paddingVertical: 0 },
  /**
   * A horizontal ScrollView carries flexGrow/flexShrink 1 of its own, so in a
   * column parent it splits the leftover height with the results below and
   * collapses when they arrive. Pinning both makes it hug its content.
   */
  stripBar: { flexGrow: 0, flexShrink: 0 },
  strip: { paddingHorizontal: metric.gutter, paddingVertical: 12, alignItems: 'center' },
  stripDivider: { width: 1, height: 18, marginHorizontal: 8 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 11,
    paddingVertical: 7,
    marginRight: 7,
  },
  count: { paddingHorizontal: metric.gutter, paddingBottom: 4 },
});
