/* EdgeForge Studio — shared utilities */

/* ---- Request context / CSRF ---- */
function getEdgeForgeCsrfToken() {
  return document.querySelector('meta[name="edgeforge-csrf-token"]')?.content || '';
}

function csrfProtectedFetch(input, init = {}) {
  const method = String(init.method || input?.method || 'GET').toUpperCase();
  const safeMethod = ['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method);
  if (safeMethod) return window.__edgeforgeOriginalFetch(input, init);

  let sameOrigin = true;
  try {
    const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    sameOrigin = url.origin === window.location.origin;
  } catch (error) {
    sameOrigin = false;
  }
  if (!sameOrigin) return window.__edgeforgeOriginalFetch(input, init);

  const token = getEdgeForgeCsrfToken();
  if (!token) return window.__edgeforgeOriginalFetch(input, init);
  const headers = new Headers(init.headers || (input?.headers ?? undefined));
  if (!headers.has('x-edgeforge-csrf-token')) {
    headers.set('x-edgeforge-csrf-token', token);
  }
  return window.__edgeforgeOriginalFetch(input, { ...init, headers });
}

if (!window.__edgeforgeOriginalFetch) {
  window.__edgeforgeOriginalFetch = window.fetch.bind(window);
  window.edgeforgeFetch = csrfProtectedFetch;
  window.fetch = csrfProtectedFetch;
}

/* ---- Dirty-state tracking ---- */
/*
 * Shared editor contract (also consumed by later wizard editors):
 * createDirtyTracker({ snapshot }) -> { markClean(), isDirty(), destroy() }.
 * The snapshot callback must return JSON-serializable state. The tracker warns
 * on tab close/browser navigation and guards in-app links while state is dirty.
 */
function createDirtyTracker({ snapshot }) {
  if (typeof snapshot !== 'function') {
    throw new TypeError('createDirtyTracker requires a snapshot function.');
  }
  let cleanSnapshot = JSON.stringify(snapshot());
  let confirmedDeparture = false;

  const isDirty = () => JSON.stringify(snapshot()) !== cleanSnapshot;
  const markClean = () => {
    cleanSnapshot = JSON.stringify(snapshot());
  };
  const beforeUnload = event => {
    if (confirmedDeparture || !isDirty()) return;
    event.preventDefault();
    event.returnValue = '';
  };
  const guardNavigation = event => {
    const target = event.target.closest?.('a[href], [data-dirty-navigation]');
    if (!target || target.hasAttribute('data-dirty-ignore') || !isDirty()) return;
    if (!window.confirm('You have unsaved changes. Leave this editor?')) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    confirmedDeparture = true;
    window.setTimeout(() => { confirmedDeparture = false; }, 0);
  };

  window.addEventListener('beforeunload', beforeUnload);
  document.addEventListener('click', guardNavigation, true);
  return {
    markClean,
    isDirty,
    destroy() {
      window.removeEventListener('beforeunload', beforeUnload);
      document.removeEventListener('click', guardNavigation, true);
    },
  };
}

window.createDirtyTracker = createDirtyTracker;

/* ---- Deterministic seed patches ---- */
function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

window.escapeHtml = escapeHtml;

// Public, DOM-free seed-patch unit. Step 2, Step 5, and later bulk
// pre-population flows share this matcher/apply contract.
window.EdgeForgeSeedPatch = window.EdgeForgeSeedPatch || (() => {
  const cloneValue = value => (
    value && typeof value === 'object' ? JSON.parse(JSON.stringify(value)) : value
  );

  const isEmpty = value => value === null || value === undefined || String(value).trim() === '';

  function normalizedName(value) {
    return fileFieldToCanonicalField(value).toLowerCase();
  }

  function hasWritableSlot(currentValue, proposedValue) {
    if (currentValue === undefined) return true;
    if (proposedValue && typeof proposedValue === 'object') {
      const currentObject = currentValue && typeof currentValue === 'object' ? currentValue : {};
      return Object.entries(proposedValue).some(([key, value]) => (
        !isEmpty(value) && isEmpty(currentObject[key])
      ));
    }
    return isEmpty(currentValue);
  }

  function matchingSlots(currentValue, proposedValue) {
    if (proposedValue && typeof proposedValue === 'object') {
      const currentObject = currentValue && typeof currentValue === 'object' ? currentValue : {};
      return Object.entries(proposedValue)
        .filter(([key, value]) => (
          !isEmpty(value)
          && !isEmpty(currentObject[key])
          && String(currentObject[key]).trim() === String(value).trim()
        ))
        .map(([key]) => key);
    }
    if (isEmpty(currentValue) || isEmpty(proposedValue)) return [];
    return String(currentValue).trim() === String(proposedValue).trim() ? ['value'] : [];
  }

  function contextFingerprint(context) {
    return JSON.stringify(context || {});
  }

  function buildRows(sourceCandidates, targetCandidates, currentFieldValues = []) {
    const sources = (sourceCandidates || [])
      .map(candidate => ({
        name: String(candidate?.name ?? candidate ?? '').trim(),
        proposedValue: candidate?.proposed_value ?? candidate?.name ?? candidate ?? '',
      }))
      .filter(source => source.name);
    const targets = (targetCandidates || [])
      .map((candidate, index) => ({
        name: String(candidate?.name ?? candidate ?? '').trim(),
        candidate,
        index,
      }))
      .filter(target => target.name);
    const exactSources = new Map();
    const exactTargets = new Map();
    sources.forEach((source, index) => {
      source.index = index;
      exactSources.set(source.name, [...(exactSources.get(source.name) || []), source]);
    });
    targets.forEach(target => {
      exactTargets.set(target.name, [...(exactTargets.get(target.name) || []), target]);
    });

    // Exact raw-name pairs have first claim. Normalized matching only sees the
    // unconsumed remainder, so accountId remains valid beside account_id.
    const exactMatches = new Map();
    const consumedSourceIndexes = new Set();
    const consumedTargetIndexes = new Set();
    exactTargets.forEach((targetMatches, name) => {
      const sourceMatches = exactSources.get(name) || [];
      if (sourceMatches.length !== 1 || targetMatches.length !== 1) return;
      exactMatches.set(targetMatches[0].index, sourceMatches[0]);
      consumedSourceIndexes.add(sourceMatches[0].index);
      consumedTargetIndexes.add(targetMatches[0].index);
    });

    const sourceGroups = new Map();
    const targetGroups = new Map();
    sources.forEach(source => {
      if (consumedSourceIndexes.has(source.index)) return;
      const key = normalizedName(source.name);
      if (!key) return;
      sourceGroups.set(key, [...(sourceGroups.get(key) || []), source]);
    });
    targets.forEach(target => {
      if (consumedTargetIndexes.has(target.index)) return;
      const key = normalizedName(target.name);
      if (!key) return;
      targetGroups.set(key, [...(targetGroups.get(key) || []), target]);
    });

    return targets.map(target => {
      const normalized = normalizedName(target.name);
      const exactSource = exactMatches.get(target.index);
      const sourceMatches = exactSource ? [exactSource] : (sourceGroups.get(normalized) || []);
      const targetMatches = exactSource ? [target] : (targetGroups.get(normalized) || []);
      const currentMatches = (currentFieldValues || []).filter(
        value => value.target_field === target.name,
      );
      const currentValue = currentMatches.find(
        value => !isEmpty(value.proposed_value),
      )?.proposed_value ?? currentMatches[0]?.proposed_value;
      const writable = hasWritableSlot(currentValue, sourceMatches[0]?.proposedValue);
      const row = {
        key: `mapping:${target.name}:${target.index}`,
        target_field: target.name,
        proposed_value: sourceMatches[0]?.proposedValue || null,
        source_field: sourceMatches[0]?.name || null,
        basis: 'left blank',
        state: 'no-match',
        checked: false,
        writable,
        matching_slots: [],
        candidate: target.candidate,
      };

      if (sourceMatches.length === 0) return row;
      if (sourceMatches.length !== 1 || targetMatches.length !== 1) {
        return {
          ...row,
          proposed_value: null,
          source_field: null,
          basis: 'multiple matches - review',
          state: 'collision',
          writable: false,
        };
      }

      const source = sourceMatches[0];
      const basis = source.name === target.name
        ? 'exact match'
        : (source.name.toLowerCase() === target.name.toLowerCase() ? 'case match' : 'snake↔camel');
      return {
        ...row,
        proposed_value: source.proposedValue,
        source_field: source.name,
        basis,
        state: 'matched',
        checked: writable,
        matching_slots: matchingSlots(currentValue, source.proposedValue),
      };
    });
  }

  function mergeIntoEmpty(currentValue, proposedValue) {
    if (proposedValue && typeof proposedValue === 'object') {
      const merged = currentValue && typeof currentValue === 'object'
        ? cloneValue(currentValue)
        : {};
      const changedSlots = [];
      Object.entries(proposedValue).forEach(([key, value]) => {
        if (isEmpty(merged[key]) && !isEmpty(value)) {
          merged[key] = cloneValue(value);
          changedSlots.push(key);
        }
      });
      return { value: merged, changed: changedSlots.length > 0, changedSlots };
    }
    if (!isEmpty(currentValue) || isEmpty(proposedValue)) {
      return { value: cloneValue(currentValue), changed: false, changedSlots: [] };
    }
    return { value: cloneValue(proposedValue), changed: true, changedSlots: ['value'] };
  }

  function applyRows(rows, currentFieldValues = [], checkedKeys = []) {
    const values = (currentFieldValues || []).map(value => ({
      ...value,
      proposed_value: cloneValue(value.proposed_value),
    }));
    const selected = new Set(checkedKeys || []);
    const applied = [];

    (rows || []).forEach(row => {
      // A forced checkbox cannot bypass collision/no-match safety.
      if (!selected.has(row.key) || row.state !== 'matched') return;
      let current = values.find(value => value.target_field === row.target_field);
      if (!current) {
        current = { target_field: row.target_field, proposed_value: undefined };
        values.push(current);
      }
      const merged = mergeIntoEmpty(current.proposed_value, row.proposed_value);
      if (!merged.changed) return;
      current.proposed_value = merged.value;
      applied.push({
        key: row.key,
        target_field: row.target_field,
        proposed_value: cloneValue(row.proposed_value),
        basis: row.basis,
        changed_slots: merged.changedSlots,
      });
    });
    return { values, applied };
  }

  return Object.freeze({
    buildRows,
    applyRows,
    contextFingerprint,
    hasWritableSlot,
    matchingSlots,
  });
})();

const derivedSeedControls = new WeakSet();

function clearDerivedSeed(control) {
  if (!control) return;
  const chip = control._edgeforgeDerivedSeedChip;
  if (chip) chip.remove();
  control._edgeforgeDerivedSeedChip = null;
}

function markDerivedSeed(control, basis) {
  if (!control) return;
  let wrapper = control.parentElement;
  if (!wrapper?.classList.contains('uxr-derived-control')) {
    wrapper = document.createElement('span');
    wrapper.className = 'uxr-derived-control';
    control.parentNode.insertBefore(wrapper, control);
    wrapper.appendChild(control);
  }
  let chip = control._edgeforgeDerivedSeedChip;
  if (!chip) {
    chip = document.createElement('span');
    chip.className = 'uxr-derived-chip';
    chip.dataset.uxrDerivedChip = 'true';
    wrapper.appendChild(chip);
    control._edgeforgeDerivedSeedChip = chip;
  }
  chip.textContent = `DERIVED · ${basis}`;
  chip.setAttribute('aria-label', `Derived value: ${basis}`);
  if (!derivedSeedControls.has(control)) {
    control.addEventListener('input', () => clearDerivedSeed(control));
    derivedSeedControls.add(control);
  }
}

function clearDownstreamMappingDerivedSeeds(card) {
  card.querySelectorAll('.mapping-row .map-source').forEach(clearDerivedSeed);
}

function recomputeDownstreamMappingDerivedSeeds(card, rows) {
  clearDownstreamMappingDerivedSeeds(card);
  const mappingRows = Array.from(card.querySelectorAll('.mapping-row'));
  (rows || []).filter(row => row.state === 'matched').forEach(seed => {
    const row = mappingRows.find(candidate => (
      candidate.querySelector('.map-target')?.value?.trim() === seed.target_field
      && candidate.querySelector('.map-source')?.value?.trim() === String(seed.proposed_value).trim()
    ));
    markDerivedSeed(row?.querySelector('.map-source'), seed.basis);
  });
}

function clearDownstreamLayoutDerivedSeeds(card) {
  card.querySelectorAll('.layout-row').forEach(row => {
    row.querySelectorAll('.layout-name, .layout-start, .layout-length').forEach(clearDerivedSeed);
  });
}

function clearDownstreamDerivedSeeds(card) {
  clearDownstreamMappingDerivedSeeds(card);
  clearDownstreamLayoutDerivedSeeds(card);
}

function recomputeDownstreamLayoutDerivedSeeds(card, rows) {
  clearDownstreamLayoutDerivedSeeds(card);
  const layoutRows = Array.from(card.querySelectorAll('.layout-row'));
  const selectors = {
    name: '.layout-name',
    start: '.layout-start',
    length: '.layout-length',
  };
  (rows || []).filter(row => row.state === 'matched').forEach(seed => {
    const row = layoutRows.find(candidate => (
      candidate.querySelector('.layout-name')?.value?.trim() === seed.target_field
    ));
    (seed.matching_slots || []).forEach(slot => {
      markDerivedSeed(row?.querySelector(selectors[slot]), seed.basis);
    });
  });
}

function renderDeterministicSeedPatch(panel, {
  title,
  description,
  rows,
  sourceLabel,
  targetLabel,
  onApply,
  isCurrent,
  onStale,
  statusId = 'save-status',
}) {
  const box = document.createElement('section');
  box.className = 'uxr-seedbox uxr-zone-derived';
  box.dataset.uxrSeedPatch = 'true';

  const heading = document.createElement('div');
  heading.className = 'uxr-seedhd';
  heading.innerHTML = `<strong>${escapeHtml(title)}</strong><p>${escapeHtml(description)}</p>`;
  box.appendChild(heading);

  if (!rows.length) {
    const empty = document.createElement('p');
    empty.className = 'uxr-seed-empty';
    empty.textContent = 'No deterministic candidates are available. Add mappings manually.';
    box.appendChild(empty);
    panel.appendChild(box);
    return box;
  }

  rows.forEach(row => {
    const item = document.createElement('label');
    item.className = `uxr-seedrow${row.state === 'no-match' ? ' blank' : ''}`;
    item.dataset.seedState = row.state;
    item.dataset.seedKey = row.key;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'uxr-seed-check';
    checkbox.checked = Boolean(row.checked);
    checkbox.disabled = row.state !== 'matched' || !row.writable;
    checkbox.setAttribute(
      'aria-label',
      `${row.state === 'matched' ? 'Apply' : 'Review'} ${row.target_field}`,
    );
    const source = document.createElement('span');
    source.className = 'uxr-seed-source';
    source.textContent = sourceLabel(row);
    const target = document.createElement('span');
    target.className = 'uxr-seed-target';
    target.textContent = targetLabel(row);
    const basis = document.createElement('span');
    basis.className = 'uxr-seed-basis';
    basis.textContent = row.state === 'matched' && !row.writable
      ? `${row.basis} · existing value kept`
      : row.basis;
    item.append(checkbox, source, target, basis);
    box.appendChild(item);
  });

  const actions = document.createElement('div');
  actions.className = 'uxr-seed-actions';
  const apply = document.createElement('button');
  apply.type = 'button';
  apply.className = 'btn btn-primary btn-sm';
  apply.textContent = 'Keep selected';
  apply.addEventListener('click', () => {
    if (isCurrent && !isCurrent()) {
      box.dataset.seedState = 'stale';
      box.querySelectorAll('.uxr-seed-check').forEach(checkbox => {
        checkbox.checked = false;
        checkbox.disabled = true;
      });
      const stale = document.createElement('p');
      stale.className = 'uxr-seed-stale';
      stale.textContent = 'These suggestions are stale. Inspect the current entity and artifact again before applying.';
      actions.replaceWith(stale);
      if (onStale) onStale();
      showStatus(statusId, stale.textContent, 'warn');
      return;
    }
    const checkedKeys = Array.from(box.querySelectorAll('.uxr-seed-check:checked'))
      .map(checkbox => checkbox.closest('.uxr-seedrow')?.dataset.seedKey)
      .filter(Boolean);
    const result = onApply(checkedKeys);
    const appliedCount = result.applied.length;
    showStatus(
      statusId,
      appliedCount
        ? `Applied ${appliedCount} deterministic seed${appliedCount === 1 ? '' : 's'} into empty fields.`
        : 'No fields changed. Existing values and unchecked rows were kept.',
      appliedCount ? 'success' : 'warn',
    );
  });
  actions.appendChild(apply);
  box.appendChild(actions);
  panel.appendChild(box);
  return box;
}

/* ---- Allowed-values paste (PR-20) ---- */
// Pure, DOM-free: splits a pasted block on comma/semicolon/tab/newline,
// trims each candidate, drops empties, and dedupes case-sensitively while
// preserving first-occurrence order (allowed values are literal tokens, so
// "CHQ" and "chq" are different values -- this never folds case).
function parseAllowedValuesPaste(text) {
  const seen = new Set();
  const values = [];
  String(text ?? '')
    .split(/[,;\t\r\n]+/)
    .forEach(raw => {
      const value = raw.trim();
      if (!value || seen.has(value)) return;
      seen.add(value);
      values.push(value);
    });
  return values;
}
window.parseAllowedValuesPaste = parseAllowedValuesPaste;

// Pure, DOM-free: union of current + pasted allowed values. Existing values
// are never dropped -- `added` is only the pasted values not already present
// (case-sensitive), appended after the current values in paste order.
function unionAllowedValuesPaste(currentValues, pastedValues) {
  const current = Array.isArray(currentValues) ? currentValues : [];
  const pasted = Array.isArray(pastedValues) ? pastedValues : [];
  const existing = new Set(current);
  const added = pasted.filter(value => !existing.has(value));
  return {
    union: [...current, ...added],
    added,
    alreadyPresent: pasted.length - added.length,
  };
}
window.unionAllowedValuesPaste = unionAllowedValuesPaste;

/* ---- Tabs ---- */
function initTabs(container) {
  const buttons = container.querySelectorAll('.tab-btn');
  const panels = container.querySelectorAll('.tab-panel');
  if (!buttons.length || !panels.length) return;
  buttons.forEach((btn, i) => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      panels.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      panels[i]?.classList.add('active');
    });
  });
  if (buttons[0] && panels[0]) buttons[0].click();
}

/* ---- Shared shell ---- */
function setShellSectionState(section, expanded) {
  document.body.dataset[`shell${section === 'rail' ? 'Rail' : 'Drawer'}`] = expanded ? 'expanded' : 'collapsed';
  document.querySelectorAll(`[data-shell-toggle="${section}"]`).forEach(button => {
    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  });
}

function toggleShellSection(section) {
  const current = document.body.dataset[`shell${section === 'rail' ? 'Rail' : 'Drawer'}`] || 'collapsed';
  setShellSectionState(section, current !== 'expanded');
}

function initShellFrame() {
  document.querySelectorAll('[data-shell-toggle="rail"]').forEach(button => {
    button.addEventListener('click', () => toggleShellSection('rail'));
  });
  document.querySelectorAll('[data-shell-toggle="drawer"]').forEach(button => {
    button.addEventListener('click', () => toggleShellSection('drawer'));
  });

  const defaultRail = document.body.dataset.shellRailDefault || 'collapsed';
  const defaultDrawer = document.body.dataset.shellDrawerDefault || 'collapsed';
  setShellSectionState('rail', defaultRail === 'expanded');
  setShellSectionState('drawer', defaultDrawer === 'expanded');
}

function initKnowledgeAssistToggle() {
  document.querySelectorAll('[data-knowledge-assist-panel]').forEach(panel => {
    const toggle = panel.querySelector('[data-knowledge-assist-toggle]');
    const label = panel.querySelector('[data-assist-toggle-label]');
    const offState = panel.querySelector('[data-assist-off-state]');
    const onState = panel.querySelector('[data-assist-on-state]');
    const actions = panel.querySelector('[data-assist-live-actions]');
    if (!toggle || !offState || !onState) return;

    const render = () => {
      const enabled = toggle.checked;
      panel.dataset.assistEnabled = enabled ? 'true' : 'false';
      offState.classList.toggle('hidden', enabled);
      onState.classList.toggle('hidden', !enabled);
      if (label) label.textContent = enabled ? 'On' : 'Off';
      if (actions && enabled && !actions.querySelector('a[href="/knowledge"]')) {
        const link = document.createElement('a');
        link.href = '/knowledge';
        link.className = 'btn btn-secondary btn-sm';
        link.textContent = 'Open Knowledge Workspace';
        actions.appendChild(link);
      }
    };

    toggle.addEventListener('change', render);
    render();
  });
}

function initKnowledgeWorkspaceModal() {
  const modal = document.querySelector('[data-knowledge-upload-modal]');
  if (!modal) return;

  const openButtons = document.querySelectorAll('[data-knowledge-modal-open]');
  const closeButtons = modal.querySelectorAll('[data-knowledge-modal-close]');
  const fileInput = modal.querySelector('input[type="file"]');

  const openModal = () => {
    modal.classList.remove('hidden');
    document.body.dataset.knowledgeModal = 'open';
    setTimeout(() => fileInput?.focus(), 0);
  };

  const closeModal = () => {
    modal.classList.add('hidden');
    delete document.body.dataset.knowledgeModal;
  };

  openButtons.forEach(button => button.addEventListener('click', openModal));
  closeButtons.forEach(button => button.addEventListener('click', closeModal));
  modal.addEventListener('click', event => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !modal.classList.contains('hidden')) closeModal();
  });
}

function initSuggestionDrawer() {
  const drawer = document.querySelector('[data-suggestion-drawer]');
  if (!drawer) return;

  const title = drawer.querySelector('[data-suggestion-drawer-title]');
  const subtitle = drawer.querySelector('[data-suggestion-drawer-subtitle]');
  const body = drawer.querySelector('[data-suggestion-drawer-body]');
  const closeButtons = drawer.querySelectorAll('[data-suggestion-drawer-close]');
  const stagedDecisions = new Map();
  let activeReviewUrl = null;
  let activeEntity = null;
  const escapeText = window.escapeHtml;

  const compactText = (value, limit = 220) => {
    const normalized = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (!normalized || normalized.length <= limit) return normalized;
    return `${normalized.slice(0, limit - 1).trimEnd()}…`;
  };

  const uniqueTextItems = values => {
    const seen = new Set();
    return (Array.isArray(values) ? values : [])
      .map(value => String(value ?? '').trim())
      .filter(value => {
        const key = value.replace(/\s+/g, ' ').toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  };

  const expandableText = (value, { summary = 'Show details', limit = 220 } = {}) => {
    const text = String(value ?? '').trim();
    if (!text) return '';
    const preview = compactText(text, limit);
    if (preview === text) return `<p>${escapeText(text)}</p>`;
    return `
      <p>${escapeText(preview)}</p>
      <details class="ka-suggestion-details">
        <summary>${escapeText(summary)}</summary>
        <pre>${escapeText(text)}</pre>
      </details>`;
  };

  const expandableList = (values, { summary = 'Show evidence details', limit = 180 } = {}) => {
    const items = uniqueTextItems(values);
    if (!items.length) return '';
    const preview = items.slice(0, 3).map(item => `<li>${escapeText(compactText(item, limit))}</li>`).join('');
    const hasLongItem = items.some(item => compactText(item, limit) !== item);
    if (items.length <= 3 && !hasLongItem) {
      return `<ul class="text-muted text-sm">${preview}</ul>`;
    }
    return `
      <ul class="text-muted text-sm">${preview}</ul>
      <details class="ka-suggestion-details">
        <summary>${escapeText(summary)}</summary>
        <ul>${items.map(item => `<li>${escapeText(item)}</li>`).join('')}</ul>
      </details>`;
  };

  const collapsedList = (values, { summary = 'View evidence' } = {}) => {
    const items = uniqueTextItems(values);
    if (!items.length) return '';
    return `
      <details class="ka-suggestion-details">
        <summary>${escapeText(summary)}</summary>
        <ul>${items.map(item => `<li>${escapeText(item)}</li>`).join('')}</ul>
      </details>`;
  };

  const conflictDocumentOptions = row => {
    const payload = row.payload || {};
    const options = Array.isArray(payload.document_options) ? payload.document_options : [];
    if (options.length) {
      return options
        .map(option => ({
          id: String(option.id || option.document_id || '').trim(),
          label: String(option.label || option.document_name || option.document_label || option.name || option.id || option.document_id || '').trim(),
        }))
        .filter(option => option.id);
    }
    const ids = Array.isArray(payload.document_ids) ? payload.document_ids : [];
    const labels = Array.isArray(payload.document_labels) ? payload.document_labels : [];
    return ids
      .map((id, index) => ({
        id: String(id || '').trim(),
        label: String(labels[index] || id || '').trim(),
      }))
      .filter(option => option.id);
  };

  const openDrawer = () => {
    drawer.classList.remove('hidden');
    drawer.setAttribute('aria-hidden', 'false');
  };

  const closeDrawer = () => {
    drawer.classList.add('hidden');
    drawer.setAttribute('aria-hidden', 'true');
  };

  const renderLoading = () => {
    if (body) body.innerHTML = '<div class="ka-suggestion-loading">Loading suggestions...</div>';
  };

  const renderEmpty = (message, warnings = []) => {
    if (body) {
      const warningItems = Array.isArray(warnings)
        ? warnings.map(item => String(item ?? '').trim()).filter(Boolean)
        : [];
      const warningMarkup = warningItems.length
        ? `<ul class="text-muted text-sm">${warningItems.map(item => `<li>${escapeText(item)}</li>`).join('')}</ul>`
        : '';
      body.innerHTML = `
        <div class="ka-suggestion-empty">
          <p>${escapeText(message || 'No suggestions are currently available for this scope.')}</p>
          ${warningMarkup}
        </div>`;
    }
  };

  const suggestionTypeForRow = row => (
    row.scope === 'cross_entity_rules'
      ? 'cross_entity_rule'
      : row.scope === 'rules'
          ? 'rule'
          : row.scope === 'validations'
            ? 'validation'
            : row.scope === 'mappings'
              ? 'mapping'
              : row.scope === 'transforms'
                ? 'transform'
                : row.scope === 'identity_role'
                  ? 'identity_role'
                : row.scope
  );

  const suggestionCategoryForRow = row => {
    if (row.payload?.already_satisfied || row.payload?.suggestion_semantics?.already_satisfied) {
      return 'Already satisfied';
    }
    if (['conflict_resolution', 'portfolio_reuse'].includes(row.scope)) {
      return 'Advisory only';
    }
    if (row.scope === 'identity_role') {
      return row.payload?.suggestion_semantics?.category
        || (row.payload?.suggested_role === 'persistence_id' ? 'Applies generated change' : 'Advisory only');
    }
    if (row.payload?.actionable === false) {
      return 'Review needed';
    }
    if (['validations', 'rules', 'cross_entity_rules', 'mappings', 'transforms'].includes(row.scope)) {
      return 'Applies generated change';
    }
    return 'Review needed';
  };

  const suggestionCategoryClass = category => {
    const normalized = String(category || '').toLowerCase();
    if (normalized.includes('already')) return 'ka-category-satisfied ka-taxonomy-satisfied';
    if (normalized.includes('advisory')) return 'ka-category-advisory ka-taxonomy-advisory';
    if (normalized.includes('evidence')) return 'ka-category-evidence ka-taxonomy-evidence';
    if (normalized.includes('generated')) return 'ka-category-generated ka-taxonomy-change';
    return 'ka-category-review ka-taxonomy-attention';
  };

  const rowKey = row => `${row.scope}:${row.suggestion_id}`;

  const payloadEditor = row => {
    if (!activeReviewUrl || !['rules', 'cross_entity_rules', 'validations', 'mappings', 'transforms', 'conflict_resolution', 'portfolio_reuse', 'identity_role'].includes(row.scope)) return '';
    if (row.scope === 'conflict_resolution') {
      const documents = conflictDocumentOptions(row);
      const selectedDocumentId = row.payload?.studio_edited_payload?.preferred_document_id || row.payload?.preferred_document_id || '';
      const resolutionNote = row.payload?.studio_edited_payload?.resolution_note || row.payload?.studio_resolution_note || '';
      const documentOptions = documents.length
        ? `<option value="">No preferred document</option>${documents.map(option => `<option value="${escapeText(option.id)}" ${option.id === selectedDocumentId ? 'selected' : ''}>${escapeText(option.label || option.id)}</option>`).join('')}`
        : '<option value="">No document ids returned</option>';
      return `
        <details class="ka-suggestion-edit">
          <summary>Record resolution note before staging</summary>
          <label class="field-label" for="conflict-note-${escapeText(row.suggestion_id || '')}">Resolution note</label>
          <textarea id="conflict-note-${escapeText(row.suggestion_id || '')}" data-conflict-resolution-note rows="4" placeholder="Describe how you reviewed or resolved this conflict.">${escapeText(resolutionNote)}</textarea>
          <label class="field-label" for="conflict-doc-${escapeText(row.suggestion_id || '')}">Preferred document (optional)</label>
          <select id="conflict-doc-${escapeText(row.suggestion_id || '')}" data-conflict-preferred-document>
            ${documentOptions}
          </select>
        </details>`;
    }
    if (row.scope === 'portfolio_reuse') {
      return `
        <details class="ka-suggestion-edit">
          <summary>Record reuse note before staging</summary>
          <label class="field-label" for="portfolio-note-${escapeText(row.suggestion_id || '')}">Reuse note</label>
          <textarea id="portfolio-note-${escapeText(row.suggestion_id || '')}" data-portfolio-reuse-note rows="3" placeholder="Describe why this portfolio pattern may be useful."></textarea>
          <label class="field-label" for="portfolio-rationale-${escapeText(row.suggestion_id || '')}">Rationale</label>
          <textarea id="portfolio-rationale-${escapeText(row.suggestion_id || '')}" data-portfolio-rationale rows="3" placeholder="Optional rationale or follow-up context."></textarea>
          <label class="field-label" for="portfolio-step-${escapeText(row.suggestion_id || '')}">Target step (optional)</label>
          <input id="portfolio-step-${escapeText(row.suggestion_id || '')}" data-portfolio-target-step type="text" placeholder="Step 3, Step 6, Step 7..." />
          <label class="field-label" for="portfolio-path-${escapeText(row.suggestion_id || '')}">Target path (optional)</label>
          <input id="portfolio-path-${escapeText(row.suggestion_id || '')}" data-portfolio-target-manifest-path type="text" placeholder="entities.Account..." />
        </details>`;
    }
    if (row.scope === 'transforms') {
      const payload = row.payload || {};
      const source = payload.source || payload.source_field || '';
      const target = payload.target || payload.target_field || '';
      const valueMap = payload.value_map ? JSON.stringify(payload.value_map) : '';
      return `
        <details class="ka-suggestion-edit">
          <summary>Edit transform row before staging</summary>
          <label class="field-label" for="transform-source-${escapeText(row.suggestion_id || '')}">Source</label>
          <input id="transform-source-${escapeText(row.suggestion_id || '')}" data-transform-source type="text" value="${escapeText(source)}" placeholder="paymentId" />
          <label class="field-label" for="transform-target-${escapeText(row.suggestion_id || '')}">Target</label>
          <input id="transform-target-${escapeText(row.suggestion_id || '')}" data-transform-target type="text" value="${escapeText(target)}" placeholder="transactionId" />
          <label class="field-label" for="transform-default-${escapeText(row.suggestion_id || '')}">Default value</label>
          <input id="transform-default-${escapeText(row.suggestion_id || '')}" data-transform-default-value type="text" value="${escapeText(payload.default_value || '')}" placeholder="optional" />
          <label class="field-label" for="transform-constant-${escapeText(row.suggestion_id || '')}">Constant</label>
          <input id="transform-constant-${escapeText(row.suggestion_id || '')}" data-transform-constant type="text" value="${escapeText(payload.constant || '')}" placeholder="optional" />
          <label class="field-label" for="transform-value-map-${escapeText(row.suggestion_id || '')}">Value map JSON</label>
          <textarea id="transform-value-map-${escapeText(row.suggestion_id || '')}" data-transform-value-map rows="3" placeholder='{"APPROVED":"A"}'>${escapeText(valueMap)}</textarea>
          <label class="field-label" for="transform-type-coercion-${escapeText(row.suggestion_id || '')}">Type coercion</label>
          <select id="transform-type-coercion-${escapeText(row.suggestion_id || '')}" data-transform-type-coercion>
            <option value="" ${payload.type_coercion ? '' : 'selected'}>None</option>
            <option value="major_to_minor_units" ${payload.type_coercion === 'major_to_minor_units' ? 'selected' : ''}>major_to_minor_units</option>
            <option value="minor_to_major_units" ${payload.type_coercion === 'minor_to_major_units' ? 'selected' : ''}>minor_to_major_units</option>
          </select>
        </details>`;
    }
    if (row.scope === 'identity_role') {
      const payload = row.payload || {};
      const selectedRole = payload.studio_edited_payload?.role || payload.suggested_role || payload.role || '';
      const roleOptions = [
        ['', 'No identity role'],
        ['persistence_id', 'persistence_id'],
        ['parent_reference', 'parent_reference'],
        ['business_key', 'business_key'],
        ['event_id', 'event_id'],
        ['idempotency_key', 'idempotency_key'],
        ['correlation_id', 'correlation_id'],
        ['external_reference', 'external_reference'],
      ].map(([value, label]) => `<option value="${escapeText(value)}" ${value === selectedRole ? 'selected' : ''}>${escapeText(label)}</option>`).join('');
      return `
        <details class="ka-suggestion-edit">
          <summary>Edit identity role before staging</summary>
          <label class="field-label" for="identity-role-${escapeText(row.suggestion_id || '')}">Identity role</label>
          <select id="identity-role-${escapeText(row.suggestion_id || '')}" data-identity-role-select>
            ${roleOptions}
          </select>
          <p class="text-muted text-sm">Only <code>persistence_id</code> changes generated identity through <code>identity_overrides</code>; other roles export as <code>metadata_only</code> identity_roles and do not change generated behavior.</p>
        </details>`;
    }
    return `
      <details class="ka-suggestion-edit">
        <summary>Edit payload before staging</summary>
        <textarea data-suggestion-payload-editor rows="8">${escapeText(JSON.stringify(row.payload || {}, null, 2))}</textarea>
      </details>`;
  };

  const actionButtons = row => {
    if (!activeReviewUrl || !['rules', 'cross_entity_rules', 'validations', 'mappings', 'transforms', 'conflict_resolution', 'portfolio_reuse', 'identity_role'].includes(row.scope)) {
      return `
        <span class="text-muted text-sm">Read-only suggestion for human review. No actions are available for this suggestion.</span>`;
    }
    if (row.payload?.actionable === false) {
      return `
        <span class="text-muted text-sm">${escapeText(row.payload.catalog_only_reason || 'Catalog-only evidence. No review actions are available.')}</span>`;
    }
    if (row.scope === 'conflict_resolution') {
      return `
        <button type="button" class="btn btn-primary btn-sm" data-suggestion-stage="accepted">Acknowledge</button>
        <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="edited">Record note</button>
        <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="rejected">Dismiss</button>`;
    }
    if (row.scope === 'portfolio_reuse') {
      return `
        <button type="button" class="btn btn-primary btn-sm" data-suggestion-stage="accepted">Acknowledge</button>
        <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="edited">Record note</button>
        <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="rejected">Dismiss</button>`;
    }
    if (row.scope === 'identity_role') {
      return `
        <button type="button" class="btn btn-primary btn-sm" data-suggestion-stage="accepted">Save Role Decision</button>
        <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="edited">Save Edited Role</button>
        <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="rejected">Reject</button>`;
    }
    return `
      <button type="button" class="btn btn-primary btn-sm" data-suggestion-stage="accepted">Apply</button>
      <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="edited">Apply edited</button>
      <button type="button" class="btn btn-secondary btn-sm" data-suggestion-stage="rejected">Reject</button>`;
  };

  const updateReviewBar = () => {
    const saveButton = drawer.querySelector('[data-suggestion-review-save]');
    const countLabel = drawer.querySelector('[data-suggestion-review-count]');
    if (saveButton) {
      saveButton.disabled = stagedDecisions.size === 0;
      saveButton.textContent = stagedDecisions.size === 0
        ? 'Save suggestion review'
        : `Save suggestion review (${stagedDecisions.size})`;
    }
    if (countLabel) {
      countLabel.textContent = stagedDecisions.size === 0
        ? 'No staged decisions yet.'
        : `${stagedDecisions.size} staged decision${stagedDecisions.size === 1 ? '' : 's'}.`;
    }
  };

  const setDrawerStatus = (message, type = 'info') => {
    const status = drawer.querySelector('[data-suggestion-review-status]');
    if (!status) return;
    status.className = `alert alert-${type}`;
    status.textContent = message || '';
    status.classList.toggle('hidden', !message);
  };

  const stageDecision = (article, status) => {
    const basePayload = JSON.parse(article.dataset.payload || '{}');
    let editedPayload = null;
    if (status === 'edited') {
      if (article.dataset.suggestionType === 'conflict_resolution') {
        const resolutionNote = article.querySelector('[data-conflict-resolution-note]')?.value?.trim() || '';
        if (!resolutionNote) {
          setDrawerStatus('Resolution note is required before staging an edited conflict review.', 'error');
          return;
        }
        const preferredDocumentId = article.querySelector('[data-conflict-preferred-document]')?.value?.trim() || '';
        const preferredDocumentLabel = article.querySelector('[data-conflict-preferred-document]')?.selectedOptions?.[0]?.textContent?.trim() || '';
        editedPayload = { resolution_note: resolutionNote };
        if (preferredDocumentId) editedPayload.preferred_document_id = preferredDocumentId;
        if (preferredDocumentId && preferredDocumentLabel) editedPayload.preferred_document_label = preferredDocumentLabel;
      } else if (article.dataset.suggestionType === 'portfolio_reuse') {
        const reuseNote = article.querySelector('[data-portfolio-reuse-note]')?.value?.trim() || '';
        const rationale = article.querySelector('[data-portfolio-rationale]')?.value?.trim() || '';
        if (!reuseNote && !rationale) {
          setDrawerStatus('Reuse note or rationale is required before staging an edited portfolio review.', 'error');
          return;
        }
        const targetStep = article.querySelector('[data-portfolio-target-step]')?.value?.trim() || '';
        const targetManifestPath = article.querySelector('[data-portfolio-target-manifest-path]')?.value?.trim() || '';
        editedPayload = {};
        if (reuseNote) editedPayload.reuse_note = reuseNote;
        if (rationale) editedPayload.rationale = rationale;
        if (targetStep) editedPayload.target_step = targetStep;
        if (targetManifestPath) editedPayload.target_manifest_path = targetManifestPath;
      } else if (article.dataset.suggestionType === 'transform') {
        const source = article.querySelector('[data-transform-source]')?.value?.trim() || '';
        const target = article.querySelector('[data-transform-target]')?.value?.trim() || '';
        const defaultValue = article.querySelector('[data-transform-default-value]')?.value?.trim() || '';
        const constant = article.querySelector('[data-transform-constant]')?.value?.trim() || '';
        const valueMapRaw = article.querySelector('[data-transform-value-map]')?.value?.trim() || '';
        const typeCoercion = article.querySelector('[data-transform-type-coercion]')?.value?.trim() || '';
        editedPayload = {
          source,
          target,
          default_value: defaultValue,
          constant,
        };
        if (typeCoercion) editedPayload.type_coercion = typeCoercion;
        if (valueMapRaw) {
          try {
            const valueMap = JSON.parse(valueMapRaw);
            if (!valueMap || Array.isArray(valueMap) || typeof valueMap !== 'object') {
              setDrawerStatus('Transform value map must be a JSON object.', 'error');
              return;
            }
            editedPayload.value_map = valueMap;
          } catch (error) {
            setDrawerStatus('Transform value map must be valid JSON before it can be staged.', 'error');
            return;
          }
        }
      } else if (article.dataset.suggestionType === 'identity_role') {
        const role = article.querySelector('[data-identity-role-select]')?.value?.trim() || '';
        if (!role) {
          setDrawerStatus('Choose an identity role before staging an edited identity suggestion.', 'error');
          return;
        }
        editedPayload = { role, suggested_role: role };
      } else {
        const raw = article.querySelector('[data-suggestion-payload-editor]')?.value || '{}';
        try {
          editedPayload = JSON.parse(raw);
        } catch (error) {
          setDrawerStatus('Edited payload must be valid JSON before it can be staged.', 'error');
          return;
        }
        if (!editedPayload || Array.isArray(editedPayload) || typeof editedPayload !== 'object') {
          setDrawerStatus('Edited payload must be a JSON object.', 'error');
          return;
        }
      }
    }

    const decision = {
      suggestion_id: article.dataset.suggestionId,
      suggestion_type: article.dataset.suggestionType,
      status,
      entity: article.dataset.entity || activeEntity || '',
      manifest_path: article.dataset.manifestPath || '',
      payload: basePayload,
    };
    if (editedPayload) decision.edited_payload = editedPayload;
    stagedDecisions.set(article.dataset.rowKey, decision);

    const rowStatus = article.querySelector('[data-suggestion-row-stage]');
    if (rowStatus) {
      rowStatus.innerHTML = `Staged decision: <code>${escapeText(status)}</code>`;
    }
    setDrawerStatus('', 'info');
    updateReviewBar();
  };

  const saveSuggestionReview = async () => {
    if (!activeReviewUrl || stagedDecisions.size === 0) return;
    setDrawerStatus('Saving staged suggestion decisions...', 'info');
    try {
      const response = await fetch(activeReviewUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions: Array.from(stagedDecisions.values()) }),
      });
      const result = await response.json();
      if (!response.ok || (result.ok === false && !result.partial_failure)) {
        const message = Array.isArray(result.errors) ? result.errors.join(' ') : result.message;
        setDrawerStatus(message || 'Suggestion review could not be saved.', 'error');
        return;
      }
      const warningText = Array.isArray(result.warnings) && result.warnings.length
        ? ` ${result.warnings.join(' ')}`
        : '';
      const errorText = Array.isArray(result.errors) && result.errors.length
        ? ` ${result.errors.join(' ')}`
        : '';
      const successfulIds = new Set(
        (result.outcomes || [])
          .filter(outcome => outcome.success)
          .map(outcome => outcome.suggestion_id)
      );
      if (!successfulIds.size && !result.partial_failure) {
        stagedDecisions.clear();
      }
      if (successfulIds.size) {
        Array.from(stagedDecisions.entries()).forEach(([key, decision]) => {
          if (successfulIds.has(decision.suggestion_id)) {
            stagedDecisions.delete(key);
          }
        });
      }
      updateReviewBar();
      setDrawerStatus(`${result.message || 'Suggestion review saved.'}${warningText}${errorText}`, result.partial_failure ? 'warn' : 'success');
      if (result.refresh || (result.applied_count || 0) > 0) {
        setTimeout(() => window.location.reload(), 1500);
      }
    } catch (error) {
      setDrawerStatus('Suggestion review request failed. Manual authoring remains available.', 'warn');
    }
  };

  const renderRows = data => {
    if (title) title.textContent = data.title || 'Suggestions';
    if (subtitle) {
      const entityText = data.entity ? ` for ${data.entity}` : '';
      subtitle.textContent = data.review_url
        ? `Stage and save Knowledge Assist suggestion decisions${entityText}.`
        : `Read-only Knowledge Assist suggestions${entityText}.`;
    }
    if (!body) return;
    stagedDecisions.clear();
    activeReviewUrl = data.review_url || null;
    activeEntity = data.entity || null;
    if (data.empty || !Array.isArray(data.scopes) || data.scopes.length === 0) {
      renderEmpty('No actionable suggestions are currently available for this scope.', data.warnings || []);
      return;
    }

    const drawerWarnings = Array.isArray(data.warnings) && data.warnings.length
      ? `<div class="alert alert-warn">${data.warnings.map(item => escapeText(item)).join('<br>')}</div>`
      : '';
    const reviewBar = activeReviewUrl ? `
      <div class="ka-suggestion-review-bar">
        <div>
          <strong>Suggestion decisions</strong>
          <div class="text-muted text-sm" data-suggestion-review-count>No staged decisions yet.</div>
        </div>
        <button type="button" class="btn btn-primary btn-sm" data-suggestion-review-save disabled>Save suggestion review</button>
      </div>
      <div class="alert hidden" data-suggestion-review-status></div>` : '';

    body.innerHTML = drawerWarnings + reviewBar + data.scopes.map(scope => {
      const rows = Array.isArray(scope.rows) ? scope.rows : [];
      const rowMarkup = rows.length ? rows.map(row => {
        const key = rowKey(row);
        const category = suggestionCategoryForRow(row);
        const confidence = row.confidence === null || row.confidence === undefined
          ? ''
          : `<span>Confidence: <strong>${escapeText(Number(row.confidence).toFixed(2))}</strong></span>`;
        const citations = `<span>Citations: <strong>${escapeText(row.citation_count ?? 0)}</strong></span>`;
        const manifestPath = row.manifest_path
          ? `<span>Path: <code>${escapeText(row.manifest_path)}</code></span>`
          : '';
        const summary = row.scope === 'conflict_resolution'
          ? ''
          : row.summary
            ? expandableText(row.summary, { summary: 'Show full rationale' })
            : '<p class="text-muted text-sm">No rationale text returned for this suggestion.</p>';
        const conflictDetails = row.scope === 'conflict_resolution' && row.payload ? (() => {
          const documents = conflictDocumentOptions(row);
          const documentLabels = documents.map(option => option.label || option.id);
          const sourceDocs = documentLabels.slice(0, 2);
          const whatDiffers = row.payload.conflict_summary || row.summary || 'Review the cited sources before finalizing this source-alignment decision.';
          return `
            <div class="ka-suggestion-advisory">
              <strong>Advisory source alignment review</strong>
              <p class="text-muted text-sm">Acknowledging this records your review decision only. It does not create a generated-app rule, does not block export, and is excluded from generated-manifest evidence links.</p>
            </div>
            <div class="ka-suggestion-what-differs">
              <strong>What differs?</strong>
              <p>${escapeText(whatDiffers)}</p>
            </div>
            <div class="ka-suggestion-row-meta">
              ${row.payload.entity ? `<span>Entity: <code>${escapeText(row.payload.entity)}</code></span>` : ''}
              ${row.payload.field ? `<span>Field: <code>${escapeText(row.payload.field)}</code></span>` : ''}
              ${row.payload.difference_category ? `<span>Difference: <strong>${escapeText(row.payload.difference_category)}</strong></span>` : ''}
              ${row.payload.normalized_field_mapping ? `<span>Mapping: <code>${escapeText(row.payload.normalized_field_mapping)}</code></span>` : ''}
              ${sourceDocs[0] ? `<span>Source A: <strong>${escapeText(sourceDocs[0])}</strong></span>` : ''}
              ${sourceDocs[1] ? `<span>Source B: <strong>${escapeText(sourceDocs[1])}</strong></span>` : ''}
              ${row.payload.conflict_query ? `<span>Query: <code>${escapeText(row.payload.conflict_query)}</code></span>` : ''}
              ${row.payload.studio_review_status ? `<span>Current review: <code>${escapeText(row.payload.studio_review_status)}</code></span>` : ''}
              ${row.payload.studio_reviewed_at ? `<span>Reviewed: <strong>${escapeText(row.payload.studio_reviewed_at)}</strong></span>` : ''}
            </div>
            ${collapsedList(row.payload.snippets, { summary: 'View evidence' })}`;
        })() : '';
        const validationDetails = row.scope === 'validations' && row.payload ? (() => {
          const field = row.payload.field || row.payload.field_name || row.payload.target_field || '';
          const validationType = row.payload.validation_type || row.payload.rule_type || row.payload.type || '';
          const updateTarget = field && validationType
            ? `${field} with ${validationType} validation`
            : 'the selected field validation metadata';
          const reviewCopy = row.payload.actionable === false
            ? (row.payload.catalog_only_reason || 'Catalog-only evidence. This validation hint will not update Studio fields.')
            : `Will update ${updateTarget} when accepted or edited. Reject records the review only.`;
          return `
            <div class="ka-suggestion-row-meta">
              ${field ? `<span>Field: <code>${escapeText(field)}</code></span>` : ''}
              ${validationType ? `<span>Validation: <code>${escapeText(validationType)}</code></span>` : ''}
              ${row.payload.studio_review_status ? `<span>Saved review: <code>${escapeText(row.payload.studio_review_status)}</code></span>` : ''}
              ${row.payload.studio_reviewed_at ? `<span>Reviewed: <strong>${escapeText(row.payload.studio_reviewed_at)}</strong></span>` : ''}
            </div>
            <p class="text-muted text-sm">${escapeText(reviewCopy)}</p>`;
        })() : '';
        const portfolioDetails = row.scope === 'portfolio_reuse' && row.payload ? `
          <div class="ka-suggestion-row-meta">
            ${row.payload.portfolio_query ? `<span>Query: <code>${escapeText(row.payload.portfolio_query)}</code></span>` : ''}
            ${row.payload.matched_project_id ? `<span>Source project: <strong>${escapeText(row.payload.matched_project_id)}</strong></span>` : ''}
            ${row.payload.reuse_kind ? `<span>Reuse kind: <strong>${escapeText(row.payload.reuse_kind)}</strong></span>` : '<span>Reuse kind: <strong>Portfolio pattern</strong></span>'}
            ${Array.isArray(row.payload.document_labels) && row.payload.document_labels.length
              ? `<span>Documents: <strong>${escapeText(row.payload.document_labels.join(', '))}</strong></span>`
              : ''}
          </div>
          ${Array.isArray(row.payload.snippets) && row.payload.snippets.length
            ? expandableList(row.payload.snippets, { summary: 'Show portfolio evidence details' })
            : '<p class="text-muted text-sm">Review only. Nothing is imported or applied yet.</p>'}`
          : '';
        const transformDetails = row.scope === 'transforms' && row.payload ? `
          <div class="ka-suggestion-row-meta">
            ${row.payload.route_name ? `<span>Route: <code>${escapeText(row.payload.route_name)}</code></span>` : ''}
            ${row.payload.target_id ? `<span>Target: <code>${escapeText(row.payload.target_id)}</code></span>` : ''}
            ${row.payload.direction ? `<span>Direction: <strong>${escapeText(row.payload.direction)}</strong></span>` : ''}
            ${(row.payload.source_field || row.payload.source) ? `<span>Source: <code>${escapeText(row.payload.source_field || row.payload.source)}</code></span>` : ''}
            ${(row.payload.target_field || row.payload.target) ? `<span>Target field: <code>${escapeText(row.payload.target_field || row.payload.target)}</code></span>` : ''}
            ${row.payload.default_value ? `<span>Default: <code>${escapeText(row.payload.default_value)}</code></span>` : ''}
            ${row.payload.constant ? `<span>Constant: <code>${escapeText(row.payload.constant)}</code></span>` : ''}
            ${row.payload.type_coercion ? `<span>Type coercion: <code>${escapeText(row.payload.type_coercion)}</code></span>` : ''}
          </div>
          ${row.payload.value_map ? `<p class="text-muted text-sm">Value map: <code>${escapeText(JSON.stringify(row.payload.value_map))}</code></p>` : ''}
          ${Array.isArray(row.payload.snippets) && row.payload.snippets.length
            ? expandableList(row.payload.snippets, { summary: 'Show transform evidence details' })
            : '<p class="text-muted text-sm">Suggested transform row. Accept or edit to apply it to this router target.</p>'}`
          : '';
        const identityRoleDetails = row.scope === 'identity_role' && row.payload ? (() => {
          const payload = row.payload || {};
          const role = payload.suggested_role || payload.role || '';
          const entity = payload.entity || data.entity || '';
          const field = payload.field || payload.field_name || payload.target_field || '';
          const semantics = payload.suggestion_semantics || {};
          const exportImpact = semantics.export_impact || (role === 'persistence_id'
            ? 'Accepting or editing this to persistence_id exports through Engine identity_overrides.'
            : 'Accepting or editing this role exports it as metadata_only identity_roles and does not change generated behavior.');
          const sourceDocs = Array.isArray(payload.source_document_names) && payload.source_document_names.length
            ? `<span>Sources: <strong>${escapeText(payload.source_document_names.join(', '))}</strong></span>`
            : '';
          return `
            <div class="ka-suggestion-row-meta">
              ${entity ? `<span>Entity: <code>${escapeText(entity)}</code></span>` : ''}
              ${field ? `<span>Field: <code>${escapeText(field)}</code></span>` : ''}
              ${role ? `<span>Suggested role: <strong>${escapeText(role)}</strong></span>` : ''}
              ${payload.review_needed ? '<span>Review needed</span>' : ''}
              ${sourceDocs}
            </div>
            <p class="text-muted text-sm">${escapeText(exportImpact)} Reject records review only and does not change manual identity decisions.</p>
            ${Array.isArray(payload.signals) && payload.signals.length
              ? `<p class="text-muted text-sm">Signals: ${escapeText(payload.signals.join(', '))}</p>`
              : ''}
            ${Array.isArray(payload.snippets) && payload.snippets.length
              ? expandableList(payload.snippets, { summary: 'Show identity-role evidence details' })
              : ''}`;
        })() : '';
        return `
          <article class="ka-suggestion-row ${category === 'Already satisfied' ? 'ka-suggestion-row-noop' : ''}"
                   data-row-key="${escapeText(key)}"
                   data-suggestion-id="${escapeText(row.suggestion_id || '')}"
                   data-suggestion-type="${escapeText(suggestionTypeForRow(row))}"
                   data-entity="${escapeText(data.entity || '')}"
                   data-manifest-path="${escapeText(row.manifest_path || '')}"
                   data-payload="${escapeText(JSON.stringify(row.payload || {}))}">
            <div class="ka-suggestion-row-topline">
              <h4>${escapeText(row.title || 'Suggestion')}</h4>
              <span class="ka-card-category ${suggestionCategoryClass(category)}">${escapeText(category)}</span>
            </div>
            <div class="ka-suggestion-row-meta">
              <span>Suggestion kind: <code>${escapeText(row.suggestion_type || row.scope || scope.scope)}</code></span>
            </div>
            ${summary}
            ${payloadEditor(row)}
            <div class="ka-suggestion-row-meta">
              <span>Status: <code>${escapeText(row.status || 'pending')}</code></span>
              ${confidence}
              ${citations}
              ${manifestPath}
            </div>
            ${conflictDetails}
            ${validationDetails}
            ${portfolioDetails}
            ${transformDetails}
            ${identityRoleDetails}
            <div class="ka-suggestion-row-actions">
              ${actionButtons(row)}
            </div>
            <div class="text-muted text-sm" data-suggestion-row-stage style="margin-top:10px">No staged decision.</div>
          </article>`;
      }).join('') : '<div class="ka-suggestion-empty">No suggestions returned for this section.</div>';

      return `
        <section class="ka-suggestion-scope">
          <div class="ka-suggestion-scope-heading">
            <h4>${escapeText(scope.label || scope.scope || 'Suggestions')}</h4>
            <span class="ka-suggestion-scope-badge">${escapeText(scope.count ?? rows.length)} item${Number(scope.count ?? rows.length) === 1 ? '' : 's'}</span>
          </div>
          ${rowMarkup}
        </section>`;
    }).join('');

    body.querySelectorAll('[data-suggestion-stage]').forEach(button => {
      button.addEventListener('click', () => {
        const article = button.closest('.ka-suggestion-row');
        if (!article) return;
        stageDecision(article, button.dataset.suggestionStage);
      });
    });
    body.querySelector('[data-suggestion-review-save]')?.addEventListener('click', saveSuggestionReview);
    updateReviewBar();
  };

  document.querySelectorAll('[data-suggestion-drawer-open]').forEach(button => {
    button.addEventListener('click', async () => {
      const url = button.getAttribute('data-suggestion-drawer-url');
      if (!url) return;
      openDrawer();
      renderLoading();
      try {
        const response = await fetch(url);
        const data = await response.json();
        if (!response.ok || data.ok === false) {
          renderEmpty(data.warning || 'Suggestion details are unavailable.', data.warnings || []);
          return;
        }
        renderRows(data);
      } catch (error) {
        renderEmpty('Suggestion details are unavailable. Manual authoring remains available.');
      }
    });
  });

  closeButtons.forEach(button => button.addEventListener('click', closeDrawer));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !drawer.classList.contains('hidden')) {
      closeDrawer();
    }
  });
}

/* ---- Mapping builder ---- */
function addMappingRow(containerId, sourceHint, targetHint) {
  const container = document.getElementById(containerId);
  const row = document.createElement('div');
  row.className = 'mapping-row';
  row.innerHTML = `
    <input type="text" placeholder="${escapeHtml(sourceHint || 'Entity.field')}" class="map-source">
    <input type="text" placeholder="${escapeHtml(targetHint || 'target_field')}" class="map-target">
    <button type="button" class="btn btn-secondary btn-sm" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(row);
}

function getMappings(containerId) {
  const container = document.getElementById(containerId);
  const rows = container.querySelectorAll('.mapping-row');
  const result = [];
  rows.forEach(row => {
    const source = row.querySelector('.map-source')?.value?.trim();
    const target = row.querySelector('.map-target')?.value?.trim();
    if (source && target) result.push({ source, target });
  });
  return result;
}

function populateMappings(containerId, mappings, sourceHint, targetHint) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  mappings.forEach(m => {
    addMappingRow(containerId, sourceHint, targetHint);
    const rows = container.querySelectorAll('.mapping-row');
    const last = rows[rows.length - 1];
    last.querySelector('.map-source').value = m.source;
    last.querySelector('.map-target').value = m.target;
  });
}

/* ---- Layout field builder ---- */
function addLayoutRow(containerId) {
  const container = document.getElementById(containerId);
  const row = document.createElement('div');
  row.className = 'mapping-row';
  row.style.gridTemplateColumns = '2fr 80px 80px auto';
  row.innerHTML = `
    <input type="text" placeholder="field_name" class="layout-name">
    <input type="number" placeholder="start" class="layout-start" min="1">
    <input type="number" placeholder="length" class="layout-length" min="1">
    <button type="button" class="btn btn-secondary btn-sm" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(row);
}

function getLayoutFields(containerId) {
  const container = document.getElementById(containerId);
  const rows = container.querySelectorAll('.mapping-row');
  const result = [];
  rows.forEach(row => {
    const name = row.querySelector('.layout-name')?.value?.trim();
    const start = parseInt(row.querySelector('.layout-start')?.value);
    const length = parseInt(row.querySelector('.layout-length')?.value);
    if (name && start > 0 && length > 0) result.push({ name, start, length });
  });
  return result;
}

/* ---- Rule builder ---- */
function addRuleRow(containerId) {
  const container = document.getElementById(containerId);
  const row = document.createElement('div');
  row.className = 'rule-row';
  row.style = 'display:grid;grid-template-columns:1fr 160px 1fr auto;gap:8px;margin-bottom:6px;align-items:center';
  row.innerHTML = `
    <input type="text" placeholder="fieldName" class="rule-field">
    <select class="rule-type" onchange="updateRuleExtras(this)">
      <option value="allowed-values">allowed-values</option>
      <option value="default">default</option>
      <option value="iso-4217">iso-4217</option>
    </select>
    <div class="rule-extras">
      <input type="text" placeholder="CHQ, SAV, CUR" class="rule-values" title="Comma-separated values">
    </div>
    <button type="button" class="btn btn-secondary btn-sm" onclick="this.parentElement.remove()">✕</button>
  `;
  container.appendChild(row);
  updateRuleExtras(row.querySelector('.rule-type'));
}

function updateRuleExtras(selectEl) {
  const row = selectEl.closest('.rule-row');
  const extrasDiv = row.querySelector('.rule-extras');
  const type = selectEl.value;
  if (type === 'allowed-values') {
    extrasDiv.innerHTML = `<input type="text" placeholder="CHQ, SAV, CUR" class="rule-values" title="Comma-separated values">`;
  } else if (type === 'default') {
    extrasDiv.innerHTML = `<input type="text" placeholder="default value" class="rule-default">`;
  } else {
    extrasDiv.innerHTML = `<span class="text-muted text-sm">No extra fields needed</span>`;
  }
}

function getRules(containerId) {
  const container = document.getElementById(containerId);
  const rows = container.querySelectorAll('.rule-row');
  const result = [];
  rows.forEach(row => {
    const field = row.querySelector('.rule-field')?.value?.trim();
    const type = row.querySelector('.rule-type')?.value;
    if (!field || !type) return;
    const entry = { field, type, values: [], value: null };
    if (type === 'allowed-values') {
      const raw = row.querySelector('.rule-values')?.value || '';
      entry.values = raw.split(',').map(v => v.trim()).filter(Boolean);
    } else if (type === 'default') {
      entry.value = row.querySelector('.rule-default')?.value?.trim() || null;
    }
    result.push(entry);
  });
  return result;
}

/* ---- API helpers ---- */
async function postJSON(url, data) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const text = await r.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (err) {
      payload = null;
    }
  }
  if (payload && typeof payload === 'object') {
    if (!r.ok && payload.ok === undefined) payload.ok = false;
    return payload;
  }
  if (!r.ok) {
    const message = text?.trim() || r.statusText || 'Unknown error';
    return { ok: false, status: r.status, errors: [`Server returned ${r.status}: ${message}`] };
  }
  return { ok: true };
}

function showStatus(elId, msg, type = 'info') {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `alert alert-${type}`;
  el.textContent = msg;
  el.classList.remove('hidden');
}

function showWarningStatusList(elId, heading, items) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = 'alert alert-warn';
  el.textContent = '';

  const strong = document.createElement('strong');
  strong.textContent = heading;
  el.appendChild(strong);

  const list = document.createElement('ul');
  list.style.margin = '6px 0 0 18px';
  items.forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    list.appendChild(li);
  });
  el.appendChild(list);
  el.classList.remove('hidden');
}

function hideStatus(elId) {
  const el = document.getElementById(elId);
  if (el) el.classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.js-tabs').forEach(initTabs);
  initShellFrame();
  initKnowledgeAssistToggle();
  initKnowledgeWorkspaceModal();
  initSuggestionDrawer();
});
