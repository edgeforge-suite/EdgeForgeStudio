function createStep3PageViewModel(bootstrap = {}) {
  const initialPhase2Interfaces = bootstrap.initialPhase2Interfaces || [];
  const INITIAL_IDENTITY_REVIEW_ENTITIES = bootstrap.initialIdentityReviewEntities || [];
  const INITIAL_KA_SUMMARY_REVIEW_STATUSES = bootstrap.initialKaSummaryReviewStatuses || {};
  const kaSummaryReviewStatuses = { ...INITIAL_KA_SUMMARY_REVIEW_STATUSES };
  const stagedKaFullFieldDecisions = new Map();
  const stagedKaFullValidationDecisions = new Map();
  const stagedKaFullIdentityDecisions = new Map();
  return {
    bootstrap: {
      paginationWrapperKeys: bootstrap.paginationWrapperKeys || [],
      kaEnabled: Boolean(bootstrap.kaEnabled),
      initialKsSelectedEntities: bootstrap.initialKsSelectedEntities || [],
      initialIdentityReviewEntities: INITIAL_IDENTITY_REVIEW_ENTITIES,
      identityRoleOptions: bootstrap.identityRoleOptions || [],
    },
    selection: {
      selectedEntityNames: [],
      matchingEntityNames: [],
      selectedOperationNames: [],
      entityOperationMap: {},
    },
    phase2: {
      interfaces: initialPhase2Interfaces,
    },
    knowledgeAssist: {
      summaryReviewStatuses: kaSummaryReviewStatuses,
      suggestionReview: {
        entity: '',
        suggestions: [],
        stagedDecisions: new Map(),
      },
      fullReview: {
        rows: [],
        filters: {
          entity: '',
          type: '',
          category: '',
          status: '',
        },
        stagedFieldDecisions: stagedKaFullFieldDecisions,
        stagedValidationDecisions: stagedKaFullValidationDecisions,
        stagedIdentityDecisions: stagedKaFullIdentityDecisions,
      },
    },
  };
}

// One page-level model owns bootstrap inputs and all mutable Step 3 client state.
const step3PageViewModel = createStep3PageViewModel(window.STEP3_ENTITIES_BOOTSTRAP || {});
const KS_EMPTY_ACTION = '<a href="/knowledge">Open Knowledge Assist workspace</a>.';

function escapeInlineJsArg(value) {
  return escapeHtml(JSON.stringify(String(value ?? '')));
}

function compactEvidenceText(value, limit = 220) {
  const normalized = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!normalized || normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit - 1).trimEnd()}…`;
}

function updateIdentityRoleImpact(selectEl) {
  const option = selectEl.selectedOptions && selectEl.selectedOptions[0];
  const row = selectEl.closest('tr');
  const target = row ? row.querySelector('.identity-role-impact') : null;
  if (!target || !option) return;
  const badge = option.dataset.impactBadge || 'No role';
  const badgeClass = option.dataset.affectsEngine === 'true' ? 'badge-ready' : 'badge-manual';
  const currentEngine = option.dataset.currentEngineBehavior || 'No generated app behavior.';
  const exportBehavior = option.dataset.exportBehavior || 'No identity-role export.';
  const apiBehavior = option.dataset.apiBehavior || '';
  target.innerHTML = `
    <span class="badge ${badgeClass}">${escapeHtml(badge)}</span>
    <div style="margin-top:4px">${escapeHtml(currentEngine)}</div>
    <div>${escapeHtml(exportBehavior)}</div>
    ${apiBehavior ? `<div>${escapeHtml(apiBehavior)}</div>` : ''}
  `;
}

function identityRoleOption(value) {
  const roleOptions = step3PageViewModel.bootstrap.identityRoleOptions;
  const options = Array.isArray(roleOptions) ? roleOptions : [];
  return options.find(option => option.value === value) || {};
}

function identityRoleImpactText(value) {
  const option = identityRoleOption(value);
  return [
    option.current_engine_behavior,
    option.export_behavior,
    option.api_behavior,
  ].filter(Boolean).join(' ') || 'No generated app behavior.';
}

function identityLensDetailForEntity(entityName) {
  return Array.from(document.querySelectorAll('[data-uxr-identity-detail]'))
    .find(detail => detail.dataset.uxrIdentityDetail === entityName) || null;
}

function applyIdentityLensVisibility(detail) {
  if (!detail) return;
  const mode = detail.dataset.uxrFilterMode || 'assigned';
  const showAll = detail.dataset.uxrShowAll === 'true';
  const search = (detail.querySelector('[data-uxr-identity-search]')?.value || '').trim().toLowerCase();
  detail.querySelectorAll('.uxr-identity-field-row').forEach(row => {
    const select = row.querySelector('.identity-role-select');
    const assigned = Boolean(select?.value);
    const nameMatches = !search || (row.dataset.uxrIdentityField || '').toLowerCase().includes(search);
    let visible = showAll || row.dataset.defaultVisible === 'true' || assigned;
    if (mode === 'id') visible = row.dataset.idLooking === 'true';
    if (mode === 'required') visible = row.dataset.required === 'true';
    row.classList.toggle('is-collapsed', !(visible && nameMatches));
  });
}

function syncIdentityLensPersistencePicker(detail) {
  if (!detail) return;
  const persistence = Array.from(detail.querySelectorAll('.identity-role-select'))
    .find(select => select.value === 'persistence_id');
  const picker = detail.querySelector('[data-uxr-persistence-picker]');
  if (picker) picker.value = persistence?.dataset.field || '';
  const ready = detail.querySelector('[data-uxr-persistence-impact-ready]');
  const fallback = detail.querySelector('[data-uxr-persistence-impact-fallback]');
  const missing = detail.querySelector('[data-uxr-persistence-impact-missing]');
  const hasModelPersistence = detail.dataset.uxrHasModelPersistence === 'true';
  if (ready) ready.hidden = !persistence;
  if (fallback) fallback.hidden = Boolean(persistence) || !hasModelPersistence;
  if (missing) missing.hidden = Boolean(persistence) || hasModelPersistence;
  const copy = detail.querySelector('[data-uxr-persistence-impact-copy]');
  const option = persistence?.selectedOptions?.[0];
  if (copy) copy.textContent = option?.dataset.currentEngineBehavior || '';
}

function chooseIdentityLensPersistenceField(picker) {
  const detail = picker.closest('[data-uxr-identity-detail]');
  if (!detail) return;
  const selectedField = picker.value || '';
  detail.querySelectorAll('.identity-role-select').forEach(select => {
    const shouldBePersistence = Boolean(selectedField) && select.dataset.field === selectedField;
    if (select.value === 'persistence_id' && !shouldBePersistence) {
      select.value = '';
      updateIdentityRoleImpact(select);
    }
    if (shouldBePersistence && select.value !== 'persistence_id') {
      select.value = 'persistence_id';
      updateIdentityRoleImpact(select);
    }
  });
  syncIdentityLensPersistencePicker(detail);
  applyIdentityLensVisibility(detail);
}

function initIdentityRoleLens() {
  const lens = document.querySelector('[data-uxr-identity-lens]');
  if (!lens) return;
  lens.querySelectorAll('[data-uxr-identity-detail]').forEach(detail => {
    syncIdentityLensPersistencePicker(detail);
    applyIdentityLensVisibility(detail);
  });
}

function appendIdentityLensRoleChip(container, label, className) {
  const chip = document.createElement('span');
  chip.className = `uxr-identity-role-chip ${className}`;
  chip.textContent = label;
  container.appendChild(chip);
}

function applyIdentityRoleLensProjection(lens, projection) {
  const stats = projection?.stats || {};
  lens.querySelectorAll('[data-uxr-identity-stat]').forEach(stat => {
    const key = stat.dataset.uxrIdentityStat || '';
    if (Object.prototype.hasOwnProperty.call(stats, key)) {
      stat.textContent = String(stats[key] ?? 0);
    }
  });

  const entities = new Map(
    (Array.isArray(projection?.entities) ? projection.entities : [])
      .map(entity => [entity.name || '', entity])
  );
  lens.querySelectorAll('[data-uxr-identity-entity]').forEach(card => {
    const entity = entities.get(card.dataset.uxrIdentityEntity || '');
    if (!entity) return;
    const fields = Array.isArray(entity.fields) ? entity.fields : [];
    const assignedCount = Number(entity.assigned_count || 0);
    const summary = card.querySelector('.text-muted.text-sm');
    if (summary) {
      summary.textContent = `${fields.length} fields · ${assignedCount} assigned role${assignedCount === 1 ? '' : 's'}`;
    }
    const chips = card.querySelector('.uxr-identity-role-chips');
    if (chips) {
      chips.replaceChildren();
      fields.forEach(field => {
        const role = field.current_role || '';
        if (!role) return;
        appendIdentityLensRoleChip(
          chips,
          role === 'persistence_id' ? 'Persistence ID' : role,
          role === 'persistence_id' ? 'is-key' : 'is-meta'
        );
      });
      if (entity.missing_key) {
        appendIdentityLensRoleChip(chips, 'No persistence key', 'is-missing');
      }
    }

    const detail = identityLensDetailForEntity(entity.name || '');
    if (!detail) return;
    const fieldsByName = new Map(fields.map(field => [field.name || '', field]));
    detail.querySelectorAll('.uxr-identity-field-row').forEach(row => {
      const field = fieldsByName.get(row.dataset.uxrIdentityField || '');
      if (!field) return;
      const select = row.querySelector('.identity-role-select');
      if (select) {
        select.value = field.current_role || '';
        updateIdentityRoleImpact(select);
      }
      const reviewed = row.querySelector('[data-uxr-identity-reviewed]');
      const reviewedAt = field.reviewed_at || '';
      if (reviewed) {
        reviewed.textContent = reviewedAt ? `Reviewed ${reviewedAt}` : '';
        reviewed.classList.toggle('hidden', !reviewedAt);
      }
      row.dataset.defaultVisible = String(Boolean(field.default_visible));
    });
    const noRoleNote = detail.querySelector('[data-uxr-no-role-note]');
    if (noRoleNote) {
      noRoleNote.textContent = `↳ ${Number(entity.collapsed_count || 0)} more fields are No role — hidden. Use Show all to review them.`;
    }
    syncIdentityLensPersistencePicker(detail);
    applyIdentityLensVisibility(detail);
  });
}

async function saveIdentityRoles() {
  const selects = Array.from(document.querySelectorAll('.identity-role-select'));
  const decisions = selects.map(selectEl => ({
    entity: selectEl.dataset.entity || '',
    field: selectEl.dataset.field || '',
    role: selectEl.value || '',
  }));
  const result = await postJSON('/entities/identity-roles', { decisions });
  if (!result.ok) {
    const detail = Array.isArray(result.errors) ? result.errors.join(' ') : (result.error || 'Could not save identity roles.');
    showStatus('identity-role-status', detail, 'error');
    return;
  }
  const lens = document.querySelector('[data-uxr-identity-lens]');
  if (!lens) {
    showStatus(
      'identity-role-status',
      `Saved ${result.saved_count || 0} identity role decision(s) to review state. persistence_id exports to identity_overrides; non-persistence roles export as metadata_only identity_roles without generated behavior.`,
      'success',
    );
    return;
  }
  applyIdentityRoleLensProjection(lens, result);
  showStatus(
    'identity-role-status',
    `Saved ${result.saved_count || 0} identity role decision(s). Identity counts and summaries are up to date.`,
    'success',
  );
}

document.addEventListener('change', event => {
  if (event.target && event.target.classList && event.target.classList.contains('identity-role-select')) {
    updateIdentityRoleImpact(event.target);
    const detail = event.target.closest('[data-uxr-identity-detail]');
    if (detail && event.target.value === 'persistence_id') {
      detail.querySelectorAll('.identity-role-select').forEach(select => {
        if (select !== event.target && select.value === 'persistence_id') {
          select.value = '';
          updateIdentityRoleImpact(select);
        }
      });
    }
    syncIdentityLensPersistencePicker(detail);
    applyIdentityLensVisibility(detail);
  }
  if (event.target && event.target.matches && event.target.matches('[data-uxr-persistence-picker]')) {
    chooseIdentityLensPersistenceField(event.target);
  }
  if (event.target && event.target.matches && event.target.matches('[data-ka-full-identity-role]')) {
    const detailsRow = event.target.closest('[data-ka-full-details-for]');
    const impact = detailsRow ? detailsRow.querySelector('[data-ka-full-identity-impact]') : null;
    if (impact) {
      impact.textContent = `${identityRoleImpactText(event.target.value || '')} Reject records review state only and does not change manual identity role decisions.`;
    }
  }
});

document.addEventListener('click', event => {
  const entityCard = event.target.closest?.('[data-uxr-identity-entity]');
  if (entityCard) {
    const lens = entityCard.closest('[data-uxr-identity-lens]');
    const entityName = entityCard.dataset.uxrIdentityEntity || '';
    lens?.querySelectorAll('[data-uxr-identity-entity]').forEach(card => {
      const selected = card === entityCard;
      card.classList.toggle('is-selected', selected);
      card.setAttribute('aria-pressed', String(selected));
    });
    lens?.querySelectorAll('[data-uxr-identity-detail]').forEach(detail => {
      detail.hidden = detail.dataset.uxrIdentityDetail !== entityName;
    });
    applyIdentityLensVisibility(identityLensDetailForEntity(entityName));
    return;
  }

  const showAll = event.target.closest?.('[data-uxr-identity-show-all]');
  if (showAll) {
    const detail = showAll.closest('[data-uxr-identity-detail]');
    const next = detail?.dataset.uxrShowAll !== 'true';
    if (detail) {
      detail.dataset.uxrShowAll = String(next);
      if (next) {
        detail.dataset.uxrFilterMode = 'assigned';
        detail.querySelectorAll('[data-uxr-identity-filter]').forEach(control => {
          control.setAttribute('aria-pressed', 'false');
        });
      }
    }
    showAll.setAttribute('aria-pressed', String(next));
    showAll.textContent = next ? 'Show assigned + exceptions' : `Show all ${detail?.querySelectorAll('.uxr-identity-field-row').length || 0} fields`;
    applyIdentityLensVisibility(detail);
    return;
  }

  const filter = event.target.closest?.('[data-uxr-identity-filter]');
  if (filter) {
    const detail = filter.closest('[data-uxr-identity-detail]');
    const requested = filter.dataset.uxrIdentityFilter || 'assigned';
    const active = filter.getAttribute('aria-pressed') === 'true';
    if (detail) {
      detail.dataset.uxrFilterMode = active ? 'assigned' : requested;
      detail.dataset.uxrShowAll = 'false';
      const showAllControl = detail.querySelector('[data-uxr-identity-show-all]');
      if (showAllControl) {
        showAllControl.setAttribute('aria-pressed', 'false');
        showAllControl.textContent = `Show all ${detail.querySelectorAll('.uxr-identity-field-row').length} fields`;
      }
    }
    detail?.querySelectorAll('[data-uxr-identity-filter]').forEach(control => {
      control.setAttribute('aria-pressed', String(control === filter && !active));
    });
    applyIdentityLensVisibility(detail);
  }
});

document.addEventListener('input', event => {
  if (event.target?.matches?.('[data-uxr-identity-search]')) {
    applyIdentityLensVisibility(event.target.closest('[data-uxr-identity-detail]'));
  }
});

function uniqueEvidenceTexts(values) {
  const seen = new Set();
  return (Array.isArray(values) ? values : [])
    .map(value => String(value ?? '').trim())
    .filter(value => {
      const key = value.replace(/\s+/g, ' ').toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function uniqueEvidenceChunks(chunks) {
  const seen = new Set();
  return (Array.isArray(chunks) ? chunks : []).filter(chunk => {
    const text = String(chunk?.snippet || chunk?.text || '').trim();
    const key = text.replace(/\s+/g, ' ').toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderExpandableEvidenceText(value, summary = 'Show details') {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const preview = compactEvidenceText(text);
  if (preview === text) return escapeHtml(text);
  return `
    ${escapeHtml(preview)}
    <details class="ka-suggestion-details">
      <summary>${escapeHtml(summary)}</summary>
      <pre>${escapeHtml(text)}</pre>
    </details>`;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function hasObjectContent(value) {
  return isPlainObject(value) && Object.keys(value).length > 0;
}

function collectTextValuesFromKeys(source, keys) {
  if (!isPlainObject(source)) return [];
  return keys.flatMap(key => {
    const value = source[key];
    if (Array.isArray(value)) {
      return value
        .map(item => (isPlainObject(item) ? '' : String(item ?? '').trim()))
        .filter(Boolean);
    }
    return String(value ?? '').trim() ? [String(value).trim()] : [];
  });
}

function suggestionPayload(detail) {
  return isPlainObject(detail?.payload) ? detail.payload : {};
}

function collectSuggestionSummary(detail) {
  const payload = suggestionPayload(detail);
  return uniqueEvidenceTexts([
    ...collectTextValuesFromKeys(detail, ['summary', 'rationale', 'confidence_basis', 'confidence_reason', 'message', 'conflict_hint']),
    ...collectTextValuesFromKeys(payload, ['summary', 'rationale', 'confidence_basis', 'confidence_reason', 'message', 'conflict_hint']),
  ]);
}

function collectSuggestionSourceLabels(detail) {
  const payload = suggestionPayload(detail);
  const labels = [];
  [detail, payload].filter(isPlainObject).forEach(source => {
    labels.push(...collectTextValuesFromKeys(source, ['source_document_names', 'document_names', 'source_labels', 'source_document_ids']));
    ['citations', 'evidence_chunks', 'source_documents', 'sources', 'documents'].forEach(key => {
      const values = source[key];
      if (!Array.isArray(values)) return;
      values.forEach(item => {
        if (!isPlainObject(item)) {
          const text = String(item ?? '').trim();
          if (text) labels.push(text);
          return;
        }
        const citation = isPlainObject(item.citation) ? item.citation : {};
        const label = (
          item.document_name || item.document_label || item.document_id ||
          item.source_name || item.name || item.title ||
          citation.document_name || citation.document_label || citation.document_id
        );
        const section = item.section || item.source_location || citation.section || citation.source_location;
        if (label) labels.push(section ? `${label} · ${section}` : String(label));
      });
    });
  });
  return uniqueEvidenceTexts(labels);
}

function collectSuggestionSnippets(detail) {
  const payload = suggestionPayload(detail);
  const snippets = [];
  [detail, payload].filter(isPlainObject).forEach(source => {
    snippets.push(...collectTextValuesFromKeys(source, ['snippet', 'evidence_snippet', 'citation_snippet']));
    ['snippets', 'evidence_snippets'].forEach(key => {
      const values = source[key];
      if (Array.isArray(values)) {
        values.forEach(item => {
          const text = isPlainObject(item) ? (item.snippet || item.text || '') : item;
          if (String(text ?? '').trim()) snippets.push(String(text).trim());
        });
      }
    });
    ['citations', 'evidence_chunks'].forEach(key => {
      const values = source[key];
      if (!Array.isArray(values)) return;
      values.forEach(item => {
        if (!isPlainObject(item)) return;
        const citation = isPlainObject(item.citation) ? item.citation : {};
        const text = item.snippet || item.text || citation.snippet || citation.text || '';
        if (String(text ?? '').trim()) snippets.push(String(text).trim());
      });
    });
  });
  return uniqueEvidenceTexts(snippets);
}

function renderSuggestionDetailList(items, className = 'ka-suggestion-detail-list') {
  const values = uniqueEvidenceTexts(items);
  if (!values.length) return '';
  return `<ul class="${escapeHtml(className)}">${values.map(item => `<li>${renderExpandableEvidenceText(item, 'Show full detail')}</li>`).join('')}</ul>`;
}

function renderSuggestionDetailsPanel(detail, options = {}) {
  const raw = isPlainObject(detail) ? detail : {};
  const normalizedPayload = hasObjectContent(options.normalizedPayload)
    ? options.normalizedPayload
    : suggestionPayload(raw);
  const sections = [];
  const summary = collectSuggestionSummary(raw);
  const sourceLabels = collectSuggestionSourceLabels(raw);
  const snippets = collectSuggestionSnippets(raw);

  if (summary.length || raw.confidence || raw.confidence_score || raw.consistency_score) {
    const confidence = raw.confidence ?? raw.confidence_score ?? raw.consistency_score;
    sections.push(`
      <section class="ka-suggestion-detail-section">
        <h5>Evidence summary</h5>
        ${renderSuggestionDetailList(summary) || '<p class="text-muted text-sm">No rationale text was returned.</p>'}
        ${confidence ? `<p class="text-muted text-sm">Confidence: <code>${escapeHtml(confidence)}</code></p>` : ''}
      </section>`);
  }
  if (sourceLabels.length || snippets.length) {
    sections.push(`
      <section class="ka-suggestion-detail-section">
        <h5>Sources and snippets</h5>
        ${sourceLabels.length ? `<strong class="text-sm">Source documents</strong>${renderSuggestionDetailList(sourceLabels)}` : ''}
        ${snippets.length ? `<strong class="text-sm">Snippets</strong>${renderSuggestionDetailList(snippets)}` : ''}
      </section>`);
  }
  if (hasObjectContent(normalizedPayload)) {
    sections.push(`
      <section class="ka-suggestion-detail-section">
        <h5>Normalized suggestion payload</h5>
        <pre>${escapeHtml(JSON.stringify(normalizedPayload, null, 2))}</pre>
      </section>`);
  }
  if (hasObjectContent(raw)) {
    sections.push(`
      <details class="ka-suggestion-details ka-suggestion-raw-json">
        <summary>Raw KS JSON</summary>
        <pre>${escapeHtml(JSON.stringify(raw, null, 2))}</pre>
      </details>`);
  }

  const body = sections.length
    ? sections.join('')
    : '<p class="text-muted text-sm">No raw evidence detail was returned for this suggestion.</p>';
  return `
    <details class="ka-suggestion-details">
      <summary>${escapeHtml(options.summary || 'Evidence and raw suggestion details')}</summary>
      ${body}
    </details>`;
}

function parseNullableValue(value) {
  if (value === true || value === 'true') return true;
  if (value === false || value === 'false') return false;
  return null;
}

function normalizeKsText(value) {
  const text = String(value ?? '').trim();
  return text ? text : null;
}

function resolveKsSuggestionFieldName(suggestion) {
  return normalizeKsText(
    suggestion?.field_name ||
    suggestion?.field ||
    suggestion?.target_field ||
    suggestion?.payload?.field_name ||
    suggestion?.payload?.field ||
    suggestion?.payload?.target_field ||
    ''
  ) || '';
}

function nullableSelectOptions(value) {
  const selected = value === true ? 'true' : value === false ? 'false' : '';
  return `
    <option value="" ${selected === '' ? 'selected' : ''}>unknown</option>
    <option value="false" ${selected === 'false' ? 'selected' : ''}>false</option>
    <option value="true" ${selected === 'true' ? 'selected' : ''}>true</option>`;
}

function displaySuggestionValue(value) {
  if (value === true || value === false) return String(value);
  const text = String(value ?? '').trim();
  return text || 'Not set';
}

function fieldChangeSummary(semantics, deltas) {
  const rows = Array.isArray(deltas) ? deltas : [];
  const parsedCompared = Number(semantics?.compared_count);
  const parsedChanged = Number(semantics?.changed_count);
  const comparedCount = Number.isFinite(parsedCompared) ? parsedCompared : rows.length;
  const changedCount = Number.isFinite(parsedChanged)
    ? parsedChanged
    : rows.filter(delta => Boolean(delta?.changed)).length;
  const comparedLabel = comparedCount === 1 ? '1 field compared' : `${comparedCount} fields compared`;
  if (!comparedCount) return 'No comparable field values';
  if (!changedCount) return `Already satisfied · ${comparedLabel}`;
  return `${changedCount} change${changedCount === 1 ? '' : 's'}, ${comparedLabel}`;
}

function fieldSuggestionCategoryClass(category) {
  const normalized = String(category || '').toLowerCase();
  if (normalized.includes('already')) return 'ka-category-satisfied ka-taxonomy-satisfied';
  if (normalized.includes('advisory')) return 'ka-category-advisory ka-taxonomy-advisory';
  if (normalized.includes('review')) return 'ka-category-review ka-taxonomy-attention';
  if (normalized.includes('evidence')) return 'ka-category-evidence ka-taxonomy-evidence';
  return 'ka-category-generated ka-taxonomy-change';
}

function setInlineAlert(elId, html) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (html) {
    el.innerHTML = html;
    el.classList.remove('hidden');
    return;
  }
  el.innerHTML = '';
  el.classList.add('hidden');
}

function currentKsEntity() {
  return document.getElementById('ks-entity-select')?.value || '';
}

function updateKsSaveButton() {
  const button = document.getElementById('ks-save-review-btn');
  if (!button) return;
  const count = step3PageViewModel.knowledgeAssist.suggestionReview.stagedDecisions.size;
  button.disabled = count === 0;
  button.textContent = count === 0
    ? 'Save suggestion review'
    : `Save suggestion review (${count})`;
}

function suggestionStageSummary(suggestionId, persistedStatus) {
  const staged = step3PageViewModel.knowledgeAssist.suggestionReview.stagedDecisions.get(suggestionId);
  const persistedLabel = persistedStatus || 'pending';
  if (!staged) {
    return `Persisted status: <code>${escapeHtml(persistedLabel)}</code>`;
  }
  return `Persisted status: <code>${escapeHtml(persistedLabel)}</code> · Staged decision: <code>${escapeHtml(staged.status)}</code>`;
}

function showKsSuggestionPanel(entities) {
  const entitySelect = document.getElementById('ks-entity-select');
  const suggestionPanel = document.getElementById('rail-suggestions-panel');
  const evidencePanel = document.getElementById('rail-evidence-panel');
  if (!entitySelect) return;

  if (!Array.isArray(entities) || entities.length === 0) {
    resetKsSuggestionProjection();
    if (suggestionPanel) suggestionPanel.classList.remove('shell-rail-panel-active');
    if (evidencePanel) evidencePanel.classList.remove('shell-rail-panel-active');
    return;
  }

  if (suggestionPanel) suggestionPanel.classList.add('shell-rail-panel-active');
  if (evidencePanel) evidencePanel.classList.add('shell-rail-panel-active');
  const previousValue = entitySelect.value;
  entitySelect.innerHTML = entities.map(entity =>
    `<option value="${escapeHtml(entity)}">${escapeHtml(entity)}</option>`
  ).join('');
  entitySelect.value = entities.includes(previousValue) ? previousValue : entities[0];
  updateKsSaveButton();
  setShellSectionState('rail', true);
  setTimeout(() => refreshKsSuggestions(), 0);
}

function resetKsSuggestionProjection(entity = '') {
  const suggestionReview = step3PageViewModel.knowledgeAssist.suggestionReview;
  suggestionReview.entity = entity;
  suggestionReview.suggestions = [];
}

function renderSuggestionCards(entity, suggestions) {
  const suggestionReview = step3PageViewModel.knowledgeAssist.suggestionReview;
  suggestionReview.entity = entity;
  suggestionReview.suggestions = (Array.isArray(suggestions) ? suggestions : [])
    .filter(suggestion => resolveKsSuggestionFieldName(suggestion));

  const container = document.getElementById('ks-suggestion-list');
  if (!container) return;
  container.innerHTML = suggestionReview.suggestions.map(suggestion => {
    const staged = suggestionReview.stagedDecisions.get(suggestion.suggestion_id);
    const resolvedFieldName = resolveKsSuggestionFieldName(suggestion);
    const consistency = Number(suggestion.consistency_score ?? 0).toFixed(2);
    const persistedStatus = suggestion.status || 'pending';
    const isActionable = suggestion.actionable !== false;
    const semantics = suggestion.suggestion_semantics || {};
    const rawCategory = semantics.category || (isActionable ? 'Applies generated change' : 'Advisory only');
    const category = rawCategory === 'Applies to generated app' ? 'Applies generated change' : rawCategory;
    const isAlreadySatisfied = Boolean(semantics.already_satisfied);
    const impacts = Array.isArray(semantics.impact) && semantics.impact.length
      ? semantics.impact
      : [isAlreadySatisfied ? 'No change. Existing model already matches Knowledge Assist evidence.' : 'Review needed'];
    const deltas = Array.isArray(semantics.deltas) ? semantics.deltas : [];
    const changeSummary = fieldChangeSummary(semantics, deltas);
    const evidenceLabel = suggestion.source_count || suggestion.has_evidence ? 'Evidence available' : 'No evidence';
    let actionMarkup = `<span class="text-muted text-sm">${escapeHtml(suggestion.catalog_only_reason || 'Catalog-only evidence for a non-current field. No review actions are available.')}</span>`;
    if (isActionable && isAlreadySatisfied) {
      actionMarkup = `
        <button type="button" class="btn btn-secondary" onclick="stageSuggestionDecision(${escapeInlineJsArg(suggestion.suggestion_id)}, 'accepted')">Mark reviewed</button>
        <button type="button" class="btn btn-secondary" onclick="stageSuggestionDecision(${escapeInlineJsArg(suggestion.suggestion_id)}, 'rejected')">Hide</button>`;
    } else if (isActionable) {
      actionMarkup = `
        <button type="button" class="btn btn-primary" onclick="stageSuggestionDecision(${escapeInlineJsArg(suggestion.suggestion_id)}, 'accepted')">Apply</button>
        <button type="button" class="btn btn-secondary" onclick="stageSuggestionDecision(${escapeInlineJsArg(suggestion.suggestion_id)}, 'rejected')">Reject</button>`;
    }

    return `
      <div class="card ks-suggestion-card ks-suggestion-card-compact ${isAlreadySatisfied ? 'ks-suggestion-card-noop' : ''}"
           data-suggestion-id="${escapeHtml(suggestion.suggestion_id)}"
           data-entity="${escapeHtml(entity)}"
           data-field-name="${escapeHtml(resolvedFieldName)}"
           data-suggested-type="${escapeHtml(suggestion.suggested_type || '')}"
           data-suggested-nullable="${suggestion.suggested_nullable === true ? 'true' : suggestion.suggested_nullable === false ? 'false' : ''}"
           data-suggested-description="${escapeHtml(suggestion.suggested_description || '')}"
           data-persisted-status="${escapeHtml(persistedStatus)}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
          <div>
            <div style="font-weight:700"><code>${escapeHtml(resolvedFieldName || 'Unknown field')}</code></div>
            <div class="text-muted text-sm">
              ${escapeHtml(changeSummary)}
              · ${escapeHtml(evidenceLabel)}
              · Status: <code>${escapeHtml(persistedStatus)}</code>
            </div>
          </div>
          <div class="ka-card-toolbar">
            <span class="ka-card-category ${fieldSuggestionCategoryClass(category)}">${escapeHtml(category)}</span>
            <button type="button" class="btn btn-secondary" onclick="loadSuggestionEvidence(${escapeInlineJsArg(suggestion.suggestion_id)}, ${escapeInlineJsArg(entity)}, ${escapeInlineJsArg(resolvedFieldName)})">Evidence</button>
            <button type="button" class="btn btn-primary" data-step3-ka-full-review-open>Open Knowledge Assist Review</button>
          </div>
        </div>

        <div class="ka-compact-summary">
          <strong>Impact:</strong> ${escapeHtml(impacts[0] || 'Review needed')}
          <span class="text-muted">· Consistency ${escapeHtml(consistency)}</span>
        </div>

        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
          ${actionMarkup}
        </div>
        <div class="text-muted text-sm ks-staged-status" style="margin-top:10px">${suggestionStageSummary(suggestion.suggestion_id, persistedStatus)}</div>
      </div>`;
  }).join('');
}

async function refreshKsSuggestions() {
  const entity = currentKsEntity();
  resetKsSuggestionProjection(entity);
  const loading = document.getElementById('ks-loading');
  const container = document.getElementById('ks-suggestion-list');
  if (!entity || !loading || !container) return;

  hideStatus('ks-review-status');
  setInlineAlert('ks-degraded', '');
  setInlineAlert('ks-empty', '');
  container.innerHTML = '';
  loading.classList.remove('hidden');

  try {
    const response = await fetch(`/entities/ks/suggestions?entity=${encodeURIComponent(entity)}`);
    const data = await response.json();
    loading.classList.add('hidden');

    if (data.degraded) {
      setInlineAlert('ks-degraded', escapeHtml(data.warning || 'Knowledge Assist is unavailable. Manual Step 3 authoring remains available.'));
      return;
    }

    if (data.empty) {
      const emptyReason = escapeHtml(data.empty_reason || `No Knowledge Assist field suggestions are currently available for ${entity}.`);
      const warnings = Array.isArray(data.warnings) && data.warnings.length
        ? `<div style="margin-top:6px">${escapeHtml(data.warnings.join(' '))}</div>`
        : '';
      setInlineAlert(
        'ks-empty',
        `${emptyReason}${warnings}${KS_EMPTY_ACTION ? ` ${KS_EMPTY_ACTION}` : ''}`
      );
      return;
    }

    if (Array.isArray(data.warnings) && data.warnings.length) {
      setInlineAlert('ks-degraded', escapeHtml(data.warnings.join(' ')));
    }
    renderSuggestionCards(entity, data.suggestions || []);
  } catch (error) {
    loading.classList.add('hidden');
    setInlineAlert('ks-degraded', 'Knowledge Assist suggestion fetch failed. Manual Step 3 authoring remains available.');
  }
}

function stageSuggestionDecision(suggestionId, status) {
  const card = Array.from(document.querySelectorAll('.ks-suggestion-card'))
    .find(candidate => candidate.dataset.suggestionId === suggestionId);
  if (!card) return;

  const decision = {
    suggestion_id: suggestionId,
    entity: card.dataset.entity,
    field_name: card.dataset.fieldName,
    status,
    suggested_type: normalizeKsText(card.dataset.suggestedType),
    suggested_nullable: parseNullableValue(card.dataset.suggestedNullable),
    suggested_description: normalizeKsText(card.dataset.suggestedDescription),
  };

  if (status === 'edited') {
    const nullableRaw = card.querySelector('.ks-edit-nullable')?.value ?? '';
    decision.edited_payload = {
      field_name: normalizeKsText(card.querySelector('.ks-edit-field-name')?.value) || card.dataset.fieldName,
      suggested_type: normalizeKsText(card.querySelector('.ks-edit-type')?.value),
      suggested_nullable: parseNullableValue(nullableRaw),
      suggested_description: normalizeKsText(card.querySelector('.ks-edit-description')?.value),
    };
  }

  step3PageViewModel.knowledgeAssist.suggestionReview.stagedDecisions.set(suggestionId, decision);
  const stagedStatus = card.querySelector('.ks-staged-status');
  if (stagedStatus) {
    stagedStatus.innerHTML = suggestionStageSummary(suggestionId, card.dataset.persistedStatus);
  }
  updateKsSaveButton();
}

async function loadSuggestionEvidence(suggestionId, entity, fieldName) {
  const container = document.getElementById('ks-evidence-viewer');
  if (!container) return;
  setShellSectionState('rail', true);
  fieldName = normalizeKsText(fieldName);
  if (!fieldName) {
    container.innerHTML = 'Evidence lookup requires a resolved current field name.';
    return;
  }
  container.dataset.loaded = 'false';
  container.innerHTML = `<strong>${escapeHtml(entity)}.${escapeHtml(fieldName)}</strong><div style="margin-top:8px">Loading evidence...</div>`;

  try {
    const response = await fetch(
      `/entities/ks/evidence?entity=${encodeURIComponent(entity)}&field_name=${encodeURIComponent(fieldName)}&suggestion_id=${encodeURIComponent(suggestionId)}`
    );
    const data = await response.json();

    if (data.degraded) {
      container.innerHTML = escapeHtml(data.warning || 'Knowledge Assist evidence lookup is unavailable.');
      return;
    }

    const definitions = (data.definitions || []).map(definition => `
      <div style="margin-top:8px">
        <strong>${escapeHtml(definition.document_name || 'Document')}</strong>
        <span class="text-muted text-sm"> · ${escapeHtml(definition.source_location || 'source')}</span><br>
        <span class="text-muted text-sm">${escapeHtml(definition.field_type || 'unknown type')} · nullable ${escapeHtml(definition.nullable)}</span>
      </div>
    `).join('');

    const evidenceChunks = uniqueEvidenceChunks(data.evidence_chunks).map(chunk => {
      const snippet = chunk.snippet || chunk.text || '';
      return `
      <div style="margin-top:8px">
        <div class="text-muted text-sm">${escapeHtml(chunk.document_name || 'Document')} · ${escapeHtml(chunk.section || chunk.source_location || 'evidence')}</div>
        <div style="margin:6px 0 0">${renderExpandableEvidenceText(snippet, 'Show full evidence text')}</div>
      </div>
    `;
    }).join('');

    container.innerHTML = `
      <div><strong>${escapeHtml(entity)}.${escapeHtml(fieldName)}</strong></div>
      <div class="text-muted text-sm" style="margin-top:4px">Evidence chain · ${escapeHtml(data.source_count || 0)} source(s)</div>
      ${definitions || '<div style="margin-top:8px" class="text-muted text-sm">No field definitions returned.</div>'}
      ${evidenceChunks || '<div style="margin-top:8px" class="text-muted text-sm">No evidence chunks returned.</div>'}
    `;
    container.dataset.loaded = 'true';
  } catch (error) {
    container.innerHTML = 'Evidence lookup failed. Manual Step 3 authoring remains available.';
  }
}

async function saveSuggestionReview(options = {}) {
  const silentIfEmpty = options.silentIfEmpty === true;
  const showSuccess = options.showSuccess !== false;
  const stagedDecisions = step3PageViewModel.knowledgeAssist.suggestionReview.stagedDecisions;

  if (stagedDecisions.size === 0) {
    const emptyResult = { ok: true, skipped: true, message: 'No staged suggestion decisions to save.' };
    if (!silentIfEmpty) {
      showStatus('ks-review-status', emptyResult.message, 'info');
    }
    return emptyResult;
  }

  try {
    const payload = {
      decisions: Array.from(stagedDecisions.values()).map(decision => {
        if (decision.status === 'edited') return decision;
        const trimmedDecision = { ...decision };
        delete trimmedDecision.edited_payload;
        return trimmedDecision;
      }),
    };
    const result = await postJSON('/entities/ks/review', payload);

    const successfulIds = new Set(
      (result.outcomes || [])
        .filter(outcome => outcome.success)
        .map(outcome => outcome.suggestion_id)
    );
    successfulIds.forEach(suggestionId => stagedDecisions.delete(suggestionId));
    updateKsSaveButton();

    await refreshKsSuggestions();

    if (result.ok) {
      if (showSuccess) {
        showStatus('ks-review-status', result.message || 'Suggestion review saved.', 'success');
      }
      return result;
    }

    let message = result.warning || result.message;
    if (!message && Array.isArray(result.errors) && result.errors.length > 0) {
      message = result.errors.join(' ');
    }
    showStatus(
      'ks-review-status',
      message || 'Suggestion review could not be saved.',
      result.degraded || result.partial_failure ? 'warn' : 'error'
    );
    return result;
  } catch (error) {
    const failure = {
      ok: false,
      degraded: true,
      warning: 'Suggestion review could not be saved because the request failed. Manual Step 3 authoring remains available.',
    };
    showStatus('ks-review-status', failure.warning, 'warn');
    return failure;
  }
}

function setKaFullReviewStatus(message, kind = 'info') {
  const status = document.querySelector('[data-ka-full-review-status]');
  if (!status) return;
  if (!message) {
    status.className = 'alert hidden';
    status.textContent = '';
    return;
  }
  status.className = `alert alert-${kind}`;
  status.textContent = message;
}

function updateKaFullReviewCount() {
  const fullReview = step3PageViewModel.knowledgeAssist.fullReview;
  const count = fullReview.stagedFieldDecisions.size
    + fullReview.stagedValidationDecisions.size
    + fullReview.stagedIdentityDecisions.size;
  const label = document.querySelector('[data-ka-full-review-count]');
  const button = document.querySelector('[data-ka-full-review-save]');
  if (label) {
    label.textContent = count === 0
      ? 'No staged decisions yet.'
      : `${count} staged decision${count === 1 ? '' : 's'}.`;
  }
  if (button) {
    button.disabled = count === 0;
    button.textContent = count === 0 ? 'Save suggestion review' : `Save suggestion review (${count})`;
  }
}

function kaFullReviewCategory(row) {
  if (row.type === 'validation') {
    return row.actionable === false ? 'Review needed' : 'Applies generated change';
  }
  if (row.type === 'identity_role') {
    const semanticCategory = row.payload?.suggestion_semantics?.category || '';
    if (row.payload?.review_needed || String(semanticCategory).toLowerCase().includes('review')) return 'Review needed';
    const role = row.payload?.suggested_role || row.payload?.role || '';
    return role === 'persistence_id' ? 'Applies generated change' : 'Studio metadata only';
  }
  const category = row.suggestion?.suggestion_semantics?.category
    || (row.suggestion?.actionable === false ? 'Review needed' : 'Applies generated change');
  return category === 'Applies to generated app' ? 'Applies generated change' : category;
}

function kaFullReviewRowKey(type, suggestionId, entity, index) {
  return `${type}:${suggestionId || entity || 'row'}:${index}`;
}

function kaFullInitialReviewStatus(type, suggestionId, manifestPath) {
  const statuses = step3PageViewModel.knowledgeAssist.summaryReviewStatuses;
  const bySuggestion = suggestionId ? statuses[`${type}:suggestion:${suggestionId}`] : '';
  if (bySuggestion) return bySuggestion;
  const byPath = manifestPath ? statuses[`${type}:path:${manifestPath}`] : '';
  return byPath || '';
}

async function loadKaFullReviewRows() {
  const rows = [];
  const warnings = [];

  try {
    const response = await fetch('/entities/ks/full-review');
    const data = await response.json();
    (data.warnings || []).forEach(warning => warnings.push(warning));
    (data.entities || []).forEach(block => {
      const entity = block.entity;
      const fieldData = block.field || {};
      (fieldData.suggestions || []).forEach((suggestion, index) => {
        if (!resolveKsSuggestionFieldName(suggestion)) return;
        const status = kaFullInitialReviewStatus('field', suggestion.suggestion_id, suggestion.manifest_path)
          || suggestion.status
          || 'pending';
        rows.push({
          key: kaFullReviewRowKey('field', suggestion.suggestion_id, entity, index),
          type: 'field',
          entity,
          suggestion,
          status,
          category: kaFullReviewCategory({ type: 'field', suggestion, status }),
        });
      });
      (fieldData.warnings || []).forEach(warning => warnings.push(`${entity}: ${warning}`));

      const validationData = block.validations || {};
      (validationData.scopes || []).forEach(scope => {
        (scope.rows || []).forEach((row, index) => {
          const payload = row.payload || {};
          const status = row.status || payload.studio_review_status || 'pending';
          const actionable = payload.actionable !== false;
          rows.push({
            key: kaFullReviewRowKey('validation', row.suggestion_id, entity, index),
            type: 'validation',
            entity,
            row,
            payload,
            actionable,
            status,
            category: kaFullReviewCategory({ type: 'validation', actionable, status }),
          });
        });
      });
      (validationData.warnings || []).forEach(warning => warnings.push(`${entity}: ${warning}`));

      const identityData = block.identity_role || null;
      if (!identityData) return;
      (identityData.scopes || []).forEach(scope => {
        (scope.rows || []).forEach((row, index) => {
          const payload = row.payload || {};
          const status = row.status || payload.studio_review_status || 'pending';
          const actionable = payload.actionable !== false;
          rows.push({
            key: kaFullReviewRowKey('identity_role', row.suggestion_id, entity, index),
            type: 'identity_role',
            entity,
            row,
            payload,
            actionable,
            status,
            category: kaFullReviewCategory({ type: 'identity_role', payload, actionable, status }),
          });
        });
      });
      (identityData.warnings || []).forEach(warning => warnings.push(`${entity}: ${warning}`));
    });
  } catch {
    warnings.push('Knowledge Assist full review could not be loaded.');
  }

  step3PageViewModel.knowledgeAssist.fullReview.rows = rows;
  renderKaFullReviewFilters(rows);
  renderKaFullReviewRows();
  setKaFullReviewStatus(warnings.length ? warnings.join(' ') : '', warnings.length ? 'warn' : 'info');
}

function renderKaFullReviewFilters(rows) {
  const entitySelect = document.querySelector('[data-ka-full-filter="entity"]');
  if (!entitySelect) return;
  const currentValue = entitySelect.value;
  const entities = Array.from(new Set(rows.map(row => row.entity).filter(Boolean))).sort();
  entitySelect.innerHTML = '<option value="">All entities</option>' + entities
    .map(entity => `<option value="${escapeHtml(entity)}">${escapeHtml(entity)}</option>`)
    .join('');
  entitySelect.value = entities.includes(currentValue) ? currentValue : '';
}

function kaFullFilterValue(name) {
  return document.querySelector(`[data-ka-full-filter="${name}"]`)?.value || '';
}

function filteredKaFullRows() {
  const filters = step3PageViewModel.knowledgeAssist.fullReview.filters;
  filters.entity = kaFullFilterValue('entity');
  filters.type = kaFullFilterValue('type');
  filters.category = kaFullFilterValue('category');
  filters.status = kaFullFilterValue('status');
  return step3PageViewModel.knowledgeAssist.fullReview.rows.filter(row => {
    if (filters.entity && row.entity !== filters.entity) return false;
    if (filters.type && row.type !== filters.type) return false;
    if (filters.category && String(row.category || '').toLowerCase() !== filters.category) return false;
    if (filters.status && String(row.status || 'pending').toLowerCase() !== filters.status) return false;
    return true;
  });
}

function kaFullImpactDisplay(category) {
  const normalized = String(category || '').toLowerCase();
  if (normalized.includes('metadata')) {
    return { label: 'Metadata', title: 'Studio metadata only / metadata-only manifest export', className: 'ka-category-advisory ka-taxonomy-advisory' };
  }
  if (normalized.includes('advisory')) {
    return { label: 'Advisory', title: 'Advisory only', className: 'ka-category-advisory ka-taxonomy-advisory' };
  }
  if (normalized.includes('already') || normalized.includes('satisfied')) {
    return { label: 'Satisfied', title: 'Already satisfied', className: 'ka-category-satisfied ka-taxonomy-satisfied' };
  }
  if (normalized.includes('review')) {
    return { label: 'Review', title: 'Review needed', className: 'ka-category-review ka-taxonomy-attention' };
  }
  return { label: 'Applies', title: 'Applies generated change', className: 'ka-category-generated ka-taxonomy-change' };
}

function kaFullEvidenceState(row) {
  const detail = row.type === 'field' ? (row.suggestion || {}) : (row.row || {});
  const payload = row.payload || detail.payload || {};
  if (detail.stale || payload.stale || detail.evidence_stale || payload.evidence_stale) return 'Stale/missing evidence';
  if (detail.evidence_unavailable || payload.evidence_unavailable || detail.missing_evidence || payload.missing_evidence) return 'Evidence unavailable';
  const evidenceCount = Number(detail.citation_count || detail.source_count || payload.citation_count || payload.source_count || 0);
  const hasEvidence = Boolean(
    detail.has_evidence ||
    row.row?.has_evidence ||
    evidenceCount > 0 ||
    collectSuggestionSourceLabels(detail).length ||
    collectSuggestionSnippets(detail).length
  );
  return hasEvidence ? 'Evidence-backed' : 'No evidence';
}

function kaFullEvidenceDisplay(state) {
  const normalized = String(state || '').toLowerCase();
  if (normalized.includes('stale') || normalized.includes('missing')) {
    return { label: 'Stale', title: 'Stale or missing evidence', className: 'ka-category-review ka-taxonomy-attention' };
  }
  if (normalized.includes('unavailable')) {
    return { label: 'Unavailable', title: 'Evidence unavailable', className: 'ka-category-review ka-taxonomy-attention' };
  }
  if (normalized.includes('backed')) {
    return { label: 'Backed', title: 'Evidence-backed', className: 'ka-category-evidence ka-taxonomy-evidence' };
  }
  return { label: 'None', title: 'No evidence', className: 'ka-category-satisfied ka-taxonomy-satisfied' };
}

function kaFullStageMap(row) {
  const fullReview = step3PageViewModel.knowledgeAssist.fullReview;
  if (row.type === 'field') return fullReview.stagedFieldDecisions;
  if (row.type === 'validation') return fullReview.stagedValidationDecisions;
  return fullReview.stagedIdentityDecisions;
}

function kaFullTypeLabel(row) {
  if (row.type === 'identity_role') return 'Identity';
  if (row.type === 'validation') return 'Validation';
  return 'Field';
}

function kaFullTargetLabel(row) {
  if (row.type === 'field') {
    return `${row.entity}.${resolveKsSuggestionFieldName(row.suggestion || {}) || 'unknown field'}`;
  }
  const payload = row.payload || {};
  const field = payload.field || payload.field_name || payload.target_field || 'unknown';
  return `${row.entity}.${field}`;
}

function kaFullFieldValueSummary(deltas, side) {
  const rows = Array.isArray(deltas) ? deltas : [];
  if (!rows.length) return 'Not returned';
  return rows.map(delta => `${delta.label || 'Field'}: ${displaySuggestionValue(delta[side])}`).join('; ');
}

function kaFullCurrentValue(row) {
  if (row.type === 'field') {
    return kaFullFieldValueSummary(row.suggestion?.suggestion_semantics?.deltas || [], 'current');
  }
  if (row.type === 'validation') {
    return row.payload?.studio_review_status ? `Saved review: ${row.payload.studio_review_status}` : 'No current value';
  }
  if (row.type === 'identity_role') {
    return row.payload?.current_role ? `Current role: ${row.payload.current_role}` : 'No current value';
  }
  return 'Not returned';
}

function kaFullSuggestedValue(row) {
  if (row.type === 'field') {
    return kaFullFieldValueSummary(row.suggestion?.suggestion_semantics?.deltas || [], 'suggested');
  }
  if (row.type === 'validation') {
    const payload = row.payload || {};
    return payload.validation_type || payload.rule_type || payload.type || 'validation';
  }
  if (row.type === 'identity_role') {
    return row.payload?.suggested_role || row.payload?.role || 'identity role';
  }
  return 'Not returned';
}

function kaFullRowSummary(row) {
  if (row.type === 'field') {
    const semantics = row.suggestion?.suggestion_semantics || {};
    const deltas = Array.isArray(semantics.deltas) ? semantics.deltas : [];
    return fieldChangeSummary(semantics, deltas);
  }
  if (row.type === 'validation') return row.row?.summary || row.row?.title || 'Validation hint';
  if (row.type === 'identity_role') return row.row?.summary || row.row?.title || 'Identity-role suggestion';
  return 'Suggestion';
}

function kaFullActionButtons(row) {
  const stageAttr = `data-ka-full-row-key="${escapeHtml(row.key)}"`;
  const detailsButton = `<button type="button" class="btn btn-secondary btn-xs" data-ka-full-toggle-details="${escapeHtml(row.key)}" aria-expanded="false">Details</button>`;
  if (row.type === 'field') {
    const suggestion = row.suggestion || {};
    const isAlreadySatisfied = Boolean(suggestion.suggestion_semantics?.already_satisfied);
    const isActionable = suggestion.actionable !== false;
    if (!isActionable) {
      return `${detailsButton}<span class="text-muted text-sm">${escapeHtml(suggestion.catalog_only_reason || 'Catalog-only evidence. No review actions are available.')}</span>`;
    }
    return isAlreadySatisfied
      ? `${detailsButton}<button type="button" class="btn btn-secondary btn-xs" data-ka-full-stage="accepted" ${stageAttr}>Mark</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-stage="rejected" ${stageAttr}>Hide</button>`
      : `${detailsButton}<button type="button" class="btn btn-primary btn-xs" data-ka-full-stage="accepted" ${stageAttr}>Apply</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-toggle-details="${escapeHtml(row.key)}" aria-expanded="false">Edit</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-stage="rejected" ${stageAttr}>Reject</button>`;
  }
  if (row.type === 'validation') {
    if (row.actionable === false) {
      return `${detailsButton}<span class="text-muted text-sm">${escapeHtml(row.payload?.catalog_only_reason || 'Catalog-only validation hint. No generated change can be applied.')}</span>`;
    }
    return `${detailsButton}<button type="button" class="btn btn-primary btn-xs" data-ka-full-stage="accepted" ${stageAttr}>Apply</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-toggle-details="${escapeHtml(row.key)}" aria-expanded="false">Edit</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-stage="rejected" ${stageAttr}>Reject</button>`;
  }
  if (row.actionable === false) {
    return `${detailsButton}<span class="text-muted text-sm">${escapeHtml(row.payload?.catalog_only_reason || 'Identity-role suggestion cannot be applied to the current CRUD model.')}</span>`;
  }
  return `${detailsButton}<button type="button" class="btn btn-primary btn-xs" data-ka-full-stage="accepted" ${stageAttr}>Save</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-toggle-details="${escapeHtml(row.key)}" aria-expanded="false">Edit</button><button type="button" class="btn btn-secondary btn-xs" data-ka-full-stage="rejected" ${stageAttr}>Reject</button>`;
}

function renderKaFullFieldDetails(row) {
  const suggestion = row.suggestion || {};
  const resolvedFieldName = resolveKsSuggestionFieldName(suggestion);
  const semantics = suggestion.suggestion_semantics || {};
  const impacts = Array.isArray(semantics.impact) && semantics.impact.length
    ? semantics.impact
    : ['Review needed'];
  const deltas = Array.isArray(semantics.deltas) ? semantics.deltas : [];
  const current = semantics.current || {};
  const suggested = semantics.suggested || {};
  const suggestedDescription = suggestion.suggested_description || suggested.description || '';
  const isAlreadySatisfied = Boolean(semantics.already_satisfied);
  const stage = step3PageViewModel.knowledgeAssist.fullReview.stagedFieldDecisions.get(row.key);
  const normalizedDetails = {
    field_name: resolvedFieldName,
    suggested_type: suggestion.suggested_type || suggested.type || '',
    suggested_nullable: suggestion.suggested_nullable ?? suggested.nullable ?? null,
    suggested_description: suggestedDescription,
    category: row.category || semantics.category || '',
    impact: impacts,
    changes: semantics.changed_count ?? deltas.filter(delta => Boolean(delta?.changed)).length,
    fields_compared: semantics.compared_count ?? deltas.length,
  };

  return `
      <div class="ka-suggestion-impact ${isAlreadySatisfied ? 'ka-suggestion-impact-muted' : ''}">
        <strong>Impact</strong>
        <ul>${impacts.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
      </div>
      ${suggestion.conflict_hint ? `<div class="alert alert-warn" style="margin-top:10px">${renderExpandableEvidenceText(suggestion.conflict_hint, 'Show full conflict detail')}</div>` : ''}
      <div class="ka-field-delta-grid">
        ${deltas.length ? deltas.map(delta => `
          <div class="ka-field-delta-row ${delta.changed === false ? 'ka-field-delta-row-matched' : ''}">
            <span class="ka-field-delta-label">${escapeHtml(delta.label || 'Field')}<small>${delta.changed === false ? 'Already matches' : 'Changed'}</small></span>
            <span><strong>Current</strong><code>${escapeHtml(displaySuggestionValue(delta.current))}</code></span>
            <span><strong>Suggested</strong><code>${escapeHtml(displaySuggestionValue(delta.suggested))}</code></span>
          </div>
        `).join('') : '<div class="text-muted text-sm">No field-level differences returned.</div>'}
      </div>
      <div class="step3-ka-edit-grid">
        <label>Field name<input type="text" data-ka-full-field-name value="${escapeHtml(stage?.edited_payload?.field_name || resolvedFieldName)}"></label>
        <label>Suggested type<input type="text" data-ka-full-field-type value="${escapeHtml(stage?.edited_payload?.suggested_type || suggestion.suggested_type || '')}"></label>
        <label>Suggested nullable<select data-ka-full-field-nullable>${nullableSelectOptions(stage?.edited_payload?.suggested_nullable ?? suggestion.suggested_nullable)}</select></label>
      </div>
      <div class="ka-description-editor step3-ka-description-wide">
        <label>Suggested description</label>
        <div class="ka-description-compare">
          <div><strong>Current</strong><p>${escapeHtml(displaySuggestionValue(current.description))}</p></div>
          <div><strong>Suggested</strong><p>${escapeHtml(displaySuggestionValue(suggested.description ?? suggestedDescription))}</p></div>
        </div>
        <textarea class="ks-edit-description" data-ka-full-field-description rows="6">${escapeHtml(stage?.edited_payload?.suggested_description ?? suggestedDescription)}</textarea>
      </div>
      ${renderSuggestionDetailsPanel(suggestion, { normalizedPayload: normalizedDetails })}
      <div class="ka-suggestion-row-actions"><button type="button" class="btn btn-primary btn-sm" data-ka-full-stage="edited" data-ka-full-row-key="${escapeHtml(row.key)}">Apply edited</button></div>
      <div class="text-muted text-sm" data-ka-full-row-stage="${escapeHtml(row.key)}">${stage ? `Staged decision: ${escapeHtml(stage.status)}` : 'No staged decision.'}</div>`;
}

function renderKaFullValidationDetails(row) {
  const payload = row.payload || {};
  const stage = step3PageViewModel.knowledgeAssist.fullReview.stagedValidationDecisions.get(row.key);
  const editablePayload = stage?.edited_payload || payload;

  return `
      <p>${escapeHtml(row.row?.summary || row.row?.title || 'Review this validation hint before applying generated validation behavior.')}</p>
      <div class="alert alert-info">
        Validation rejects record review state only. If a KA-applied rule already exists, it remains in Step 6 until removed there.
      </div>
      <details class="ka-suggestion-edit" open>
        <summary>Edit validation payload</summary>
        <textarea data-ka-full-validation-payload rows="8">${escapeHtml(JSON.stringify(editablePayload, null, 2))}</textarea>
      </details>
      ${renderSuggestionDetailsPanel(row.row || {}, {
        summary: 'Evidence and raw validation details',
        normalizedPayload: payload,
      })}
      <div class="ka-suggestion-row-actions"><button type="button" class="btn btn-primary btn-sm" data-ka-full-stage="edited" data-ka-full-row-key="${escapeHtml(row.key)}">Apply edited</button></div>
      <div class="text-muted text-sm" data-ka-full-row-stage="${escapeHtml(row.key)}">${stage ? `Staged decision: ${escapeHtml(stage.status)}` : 'No staged decision.'}</div>`;
}

function renderKaFullIdentityRoleDetails(row) {
  const payload = row.payload || {};
  const role = payload.suggested_role || payload.role || '';
  const stage = step3PageViewModel.knowledgeAssist.fullReview.stagedIdentityDecisions.get(row.key);
  const selectedRole = stage?.edited_payload?.role || role;
  const roleOptionsModel = step3PageViewModel.bootstrap.identityRoleOptions;
  const optionModels = Array.isArray(roleOptionsModel) ? roleOptionsModel : [];
  const roleOptions = optionModels.map(option => {
    const value = String(option.value || '');
    const label = String(option.label || value || 'No identity role');
    return `<option value="${escapeHtml(value)}" ${value === selectedRole ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
  const exportImpact = identityRoleImpactText(selectedRole);

  return `
      <p>${escapeHtml(row.row?.summary || row.row?.title || 'Review this identity-role suggestion before applying it to Studio identity decisions.')}</p>
      <div class="alert alert-info" data-ka-full-identity-impact>
        ${escapeHtml(exportImpact)} Reject records review state only and does not change manual identity role decisions.
      </div>
      <label class="field-label">Identity role</label>
      <select data-ka-full-identity-role>${roleOptions}</select>
      ${renderSuggestionDetailsPanel(row.row || {}, {
        summary: 'Evidence and raw identity-role details',
        normalizedPayload: payload,
      })}
      <div class="ka-suggestion-row-actions"><button type="button" class="btn btn-primary btn-sm" data-ka-full-stage="edited" data-ka-full-row-key="${escapeHtml(row.key)}">Save Edited Role</button></div>
      <div class="text-muted text-sm" data-ka-full-row-stage="${escapeHtml(row.key)}">${stage ? `Staged decision: ${escapeHtml(stage.status)}` : 'No staged decision.'}</div>`;
}

function renderKaFullRowDetails(row) {
  if (row.type === 'validation') return renderKaFullValidationDetails(row);
  if (row.type === 'identity_role') return renderKaFullIdentityRoleDetails(row);
  return renderKaFullFieldDetails(row);
}

function renderKaFullTableRow(row) {
  const stage = kaFullStageMap(row).get(row.key);
  const impact = kaFullImpactDisplay(row.category);
  const evidence = kaFullEvidenceDisplay(kaFullEvidenceState(row));
  const detailsId = `ka-full-details-${String(row.key).replace(/[^a-z0-9_-]+/gi, '-')}`;
  return `
    <tr class="step3-ka-review-table-row ${impact.label === 'Satisfied' ? 'ka-suggestion-row-noop' : ''}"
        data-ka-full-row
        data-entity="${escapeHtml(row.entity)}"
        data-type="${escapeHtml(row.type)}"
        data-category="${escapeHtml(String(row.category || '').toLowerCase())}"
        data-status="${escapeHtml(row.status || 'pending')}"
        data-row-key="${escapeHtml(row.key)}">
      <td><span class="ka-suggestion-scope-badge">${escapeHtml(kaFullTypeLabel(row))}</span><div class="text-muted text-xs">Status <code>${escapeHtml(row.status || 'pending')}</code></div></td>
      <td><strong>${escapeHtml(kaFullTargetLabel(row))}</strong><div class="text-muted text-xs ka-line-clamp-1">${escapeHtml(kaFullRowSummary(row))}</div></td>
      <td><div class="step3-ka-review-value" title="${escapeHtml(kaFullCurrentValue(row))}">${escapeHtml(kaFullCurrentValue(row))}</div></td>
      <td><div class="step3-ka-review-value" title="${escapeHtml(kaFullSuggestedValue(row))}">${escapeHtml(kaFullSuggestedValue(row))}</div></td>
      <td><span class="ka-card-category ka-card-category-compact ${impact.className}" title="${escapeHtml(impact.title)}" aria-label="${escapeHtml(impact.title)}">${escapeHtml(impact.label)}</span></td>
      <td><span class="ka-card-category ka-card-category-compact ${evidence.className}" title="${escapeHtml(evidence.title)}" aria-label="${escapeHtml(evidence.title)}">${escapeHtml(evidence.label)}</span></td>
      <td>
        <div class="step3-ka-review-actions">${kaFullActionButtons(row)}</div>
        <div class="text-muted text-xs" data-ka-full-row-stage="${escapeHtml(row.key)}">${stage ? `Staged: ${escapeHtml(stage.status)}` : 'No staged decision'}</div>
      </td>
    </tr>
    <tr class="step3-ka-review-details-row" id="${escapeHtml(detailsId)}" data-ka-full-details-for="${escapeHtml(row.key)}" hidden>
      <td colspan="7">
        <div class="step3-ka-review-details-card">
          ${renderKaFullRowDetails(row)}
        </div>
      </td>
    </tr>`;
}

function renderKaFullReviewRows() {
  const body = document.querySelector('[data-ka-full-review-body]');
  if (!body) return;
  const rows = filteredKaFullRows();
  if (!rows.length) {
    body.innerHTML = '<div class="ka-suggestion-empty">No Step 3 suggestions match the current filters.</div>';
    return;
  }
  body.innerHTML = `
    <div class="step3-ka-review-table-shell">
      <table class="step3-ka-review-table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Target</th>
            <th>Current</th>
            <th>Suggested</th>
            <th>Impact</th>
            <th>Evidence</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>${rows.map(renderKaFullTableRow).join('')}</tbody>
      </table>
    </div>`;
}

function kaFullElementForRow(selector, rowKey, datasetKey) {
  return Array.from(document.querySelectorAll(selector))
    .find(item => item.dataset[datasetKey] === rowKey);
}

function toggleKaFullReviewDetails(rowKey) {
  const detailsRow = kaFullElementForRow('[data-ka-full-details-for]', rowKey, 'kaFullDetailsFor');
  if (!detailsRow) return;
  const willOpen = detailsRow.hidden;
  detailsRow.hidden = !willOpen;
  document.querySelectorAll(`[data-ka-full-toggle-details]`).forEach(button => {
    if (button.dataset.kaFullToggleDetails !== rowKey) return;
    button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    button.textContent = willOpen && button.textContent === 'Details' ? 'Hide' : button.textContent === 'Hide' ? 'Details' : button.textContent;
  });
}

function stageKaFullReviewDecision(rowKey, status) {
  const fullReview = step3PageViewModel.knowledgeAssist.fullReview;
  const row = fullReview.rows.find(item => item.key === rowKey);
  const tableRow = kaFullElementForRow('[data-ka-full-row]', rowKey, 'rowKey');
  const detailsRow = kaFullElementForRow('[data-ka-full-details-for]', rowKey, 'kaFullDetailsFor');
  const inputRoot = detailsRow || tableRow;
  if (!row || !tableRow || !inputRoot) return;

  if (row.type === 'field') {
    const suggestion = row.suggestion || {};
    const resolvedFieldName = resolveKsSuggestionFieldName(suggestion);
    const decision = {
      suggestion_id: suggestion.suggestion_id,
      entity: row.entity,
      field_name: resolvedFieldName,
      status,
      suggested_type: normalizeKsText(suggestion.suggested_type),
      suggested_nullable: parseNullableValue(suggestion.suggested_nullable),
      suggested_description: normalizeKsText(suggestion.suggested_description),
    };
    if (status === 'edited') {
      decision.edited_payload = {
        field_name: normalizeKsText(inputRoot.querySelector('[data-ka-full-field-name]')?.value) || resolvedFieldName,
        suggested_type: normalizeKsText(inputRoot.querySelector('[data-ka-full-field-type]')?.value),
        suggested_nullable: parseNullableValue(inputRoot.querySelector('[data-ka-full-field-nullable]')?.value),
        suggested_description: normalizeKsText(inputRoot.querySelector('[data-ka-full-field-description]')?.value),
      };
    }
    fullReview.stagedFieldDecisions.set(rowKey, decision);
  } else if (row.type === 'validation') {
    const validationRow = row.row || {};
    const payload = row.payload || {};
    const decision = {
      suggestion_id: validationRow.suggestion_id,
      suggestion_type: 'validation',
      status,
      entity: row.entity,
      payload,
    };
    if (status === 'edited') {
      try {
        decision.edited_payload = JSON.parse(inputRoot.querySelector('[data-ka-full-validation-payload]')?.value || '{}');
      } catch {
        setKaFullReviewStatus('Edited validation payload must be valid JSON before it can be staged.', 'error');
        return;
      }
    }
    fullReview.stagedValidationDecisions.set(rowKey, decision);
  } else {
    const identityRow = row.row || {};
    const payload = row.payload || {};
    const decision = {
      suggestion_id: identityRow.suggestion_id,
      suggestion_type: 'identity_role',
      status,
      entity: row.entity,
      payload,
    };
    if (status === 'edited') {
      const role = inputRoot.querySelector('[data-ka-full-identity-role]')?.value?.trim() || '';
      if (!role) {
        setKaFullReviewStatus('Choose an identity role before staging an edited identity suggestion.', 'error');
        return;
      }
      decision.edited_payload = { role, suggested_role: role };
    }
    fullReview.stagedIdentityDecisions.set(rowKey, decision);
  }

  document.querySelectorAll('[data-ka-full-row-stage]').forEach(label => {
    if (label.dataset.kaFullRowStage === rowKey) {
      label.textContent = label.closest('tr')?.matches('[data-ka-full-row]') ? `Staged: ${status}` : `Staged decision: ${status}`;
    }
  });
  updateKaFullReviewCount();
}

function kaFullReviewResultMessage(result, fallback) {
  if (Array.isArray(result.errors) && result.errors.length > 0) {
    return result.errors.join(' ');
  }
  return result.warning || result.message || fallback;
}

function kaFullSuccessfulRowKeys(stagedMap, result) {
  const successfulIds = new Set(
    (result.outcomes || [])
      .filter(outcome => outcome.success)
      .map(outcome => outcome.suggestion_id)
  );
  if (!successfulIds.size && result.ok && !result.partial_failure) {
    return Array.from(stagedMap.keys());
  }
  return Array.from(stagedMap.entries())
    .filter(([, decision]) => successfulIds.has(decision.suggestion_id))
    .map(([rowKey]) => rowKey);
}

function updateKaSummaryCount(type, status, delta) {
  if (!['accepted', 'edited', 'rejected'].includes(status)) return;
  const countNode = document.querySelector(`[data-ka-summary-type="${type}"] [data-ka-summary-status="${status}"]`);
  if (!countNode) return;
  const current = Number.parseInt(countNode.textContent || '0', 10) || 0;
  countNode.textContent = String(Math.max(0, current + delta));
}

function applyKaSummaryReviewUpdates(stagedMap, successfulRowKeys) {
  const kaSummaryReviewStatuses = step3PageViewModel.knowledgeAssist.summaryReviewStatuses;
  successfulRowKeys.forEach(rowKey => {
    const decision = stagedMap.get(rowKey);
    const row = step3PageViewModel.knowledgeAssist.fullReview.rows.find(item => item.key === rowKey);
    if (!decision || !row || !['field', 'validation', 'identity_role'].includes(row.type)) return;
    const previousStatus = String(row.status || 'pending').toLowerCase();
    const nextStatus = String(decision.status || '').toLowerCase();
    if (!['accepted', 'edited', 'rejected'].includes(nextStatus)) return;
    if (previousStatus !== nextStatus && ['accepted', 'edited', 'rejected'].includes(previousStatus)) {
      updateKaSummaryCount(row.type, previousStatus, -1);
    }
    if (previousStatus !== nextStatus) {
      updateKaSummaryCount(row.type, nextStatus, 1);
      row.status = nextStatus;
    }
    if (decision.suggestion_id) {
      kaSummaryReviewStatuses[`${row.type}:suggestion:${decision.suggestion_id}`] = nextStatus;
    }
    const manifestPath = row.type === 'field' ? row.suggestion?.manifest_path : row.row?.manifest_path;
    if (manifestPath) {
      kaSummaryReviewStatuses[`${row.type}:path:${manifestPath}`] = nextStatus;
    }
  });
}

function clearSuccessfulKaFullDecisions(stagedMap, result) {
  const successfulRowKeys = kaFullSuccessfulRowKeys(stagedMap, result);
  if (successfulRowKeys.length === stagedMap.size && result.ok && !result.partial_failure) {
    stagedMap.clear();
    return;
  }
  successfulRowKeys.forEach(rowKey => {
    if (stagedMap.has(rowKey)) {
      stagedMap.delete(rowKey);
    }
  });
}

async function saveKaFullReview() {
  const fullReview = step3PageViewModel.knowledgeAssist.fullReview;
  const stagedKaFullFieldDecisions = fullReview.stagedFieldDecisions;
  const stagedKaFullValidationDecisions = fullReview.stagedValidationDecisions;
  const stagedKaFullIdentityDecisions = fullReview.stagedIdentityDecisions;
  if (stagedKaFullFieldDecisions.size === 0 && stagedKaFullValidationDecisions.size === 0 && stagedKaFullIdentityDecisions.size === 0) return;
  setKaFullReviewStatus('Saving staged Step 3 Knowledge Assist decisions...', 'info');
  const messages = [];
  let hadFailure = false;

  if (stagedKaFullFieldDecisions.size) {
    const result = await postJSON('/entities/ks/review', {
      decisions: Array.from(stagedKaFullFieldDecisions.values()).map(decision => {
        if (decision.status === 'edited') return decision;
        const trimmed = { ...decision };
        delete trimmed.edited_payload;
        return trimmed;
      }),
    });
    messages.push(kaFullReviewResultMessage(result, 'Field suggestion review saved.'));
    applyKaSummaryReviewUpdates(stagedKaFullFieldDecisions, kaFullSuccessfulRowKeys(stagedKaFullFieldDecisions, result));
    clearSuccessfulKaFullDecisions(stagedKaFullFieldDecisions, result);
    hadFailure = hadFailure || !result.ok || Boolean(result.partial_failure);
  }

  if (stagedKaFullValidationDecisions.size) {
    const result = await postJSON('/entities/ks/validation-review', {
      decisions: Array.from(stagedKaFullValidationDecisions.values()).map(decision => {
        if (decision.status === 'edited') return decision;
        const trimmed = { ...decision };
        delete trimmed.edited_payload;
        return trimmed;
      }),
    });
    messages.push(kaFullReviewResultMessage(result, 'Validation hint review saved.'));
    applyKaSummaryReviewUpdates(stagedKaFullValidationDecisions, kaFullSuccessfulRowKeys(stagedKaFullValidationDecisions, result));
    clearSuccessfulKaFullDecisions(stagedKaFullValidationDecisions, result);
    hadFailure = hadFailure || !result.ok || Boolean(result.partial_failure);
  }

  if (stagedKaFullIdentityDecisions.size) {
    const result = await postJSON('/entities/ks/identity-role-review', {
      decisions: Array.from(stagedKaFullIdentityDecisions.values()).map(decision => {
        if (decision.status === 'edited') return decision;
        const trimmed = { ...decision };
        delete trimmed.edited_payload;
        return trimmed;
      }),
    });
    const lens = document.querySelector('[data-uxr-identity-lens]');
    if (lens && result.stats && Array.isArray(result.entities)) {
      applyIdentityRoleLensProjection(lens, result);
    }
    messages.push(kaFullReviewResultMessage(result, 'Identity-role suggestion review saved.'));
    applyKaSummaryReviewUpdates(stagedKaFullIdentityDecisions, kaFullSuccessfulRowKeys(stagedKaFullIdentityDecisions, result));
    clearSuccessfulKaFullDecisions(stagedKaFullIdentityDecisions, result);
    hadFailure = hadFailure || !result.ok || Boolean(result.partial_failure);
  }

  updateKaFullReviewCount();
  await loadKaFullReviewRows();
  await refreshKsSuggestions();
  setKaFullReviewStatus(messages.join(' '), hadFailure ? 'warn' : 'success');
}

async function openStep3KaFullReview() {
  const modal = document.querySelector('[data-step3-ka-full-review]');
  const body = document.querySelector('[data-ka-full-review-body]');
  if (!modal || !body) return;
  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
  body.innerHTML = '<div class="ka-suggestion-loading">Loading Step 3 Knowledge Assist review...</div>';
  await loadKaFullReviewRows();
}

function closeStep3KaFullReview() {
  const modal = document.querySelector('[data-step3-ka-full-review]');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
}

document.addEventListener('click', event => {
  const openButton = event.target.closest('[data-step3-ka-full-review-open]');
  if (openButton) {
    event.preventDefault();
    openStep3KaFullReview();
    return;
  }
  if (event.target.closest('[data-step3-ka-full-review-close]')) {
    event.preventDefault();
    closeStep3KaFullReview();
    return;
  }
  const detailsButton = event.target.closest('[data-ka-full-toggle-details]');
  if (detailsButton) {
    event.preventDefault();
    toggleKaFullReviewDetails(detailsButton.dataset.kaFullToggleDetails);
    return;
  }
  const stageButton = event.target.closest('[data-ka-full-stage]');
  if (stageButton) {
    event.preventDefault();
    stageKaFullReviewDecision(stageButton.dataset.kaFullRowKey, stageButton.dataset.kaFullStage);
  }
});

document.querySelectorAll('[data-ka-full-filter]').forEach(filter => {
  filter.addEventListener('change', renderKaFullReviewRows);
});
document.querySelector('[data-ka-full-refresh]')?.addEventListener('click', loadKaFullReviewRows);
document.querySelector('[data-ka-full-review-save]')?.addEventListener('click', saveKaFullReview);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeStep3KaFullReview();
});

function detectPaginationWrapperFields(content) {
  if (!content) return [];
  try {
    const parsed = JSON.parse(content);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return [];
    if (!Object.prototype.hasOwnProperty.call(parsed, 'content') || !Array.isArray(parsed.content)) return [];
    const presentKeys = step3PageViewModel.bootstrap.paginationWrapperKeys
      .filter(key => Object.prototype.hasOwnProperty.call(parsed, key));
    const hasMetadataKey = presentKeys.some(key => key !== 'content');
    return hasMetadataKey ? presentKeys : [];
  } catch {
    return [];
  }
}

function refreshPaginationWrapperGuidance(panel, ifaceName, opName, initialFields) {
  const warningEl = Array.from(panel.querySelectorAll('.pagination-wrapper-guidance'))
    .find(candidate => candidate.dataset.iface === ifaceName && candidate.dataset.op === opName);
  const responseTextarea = Array.from(panel.querySelectorAll('textarea[data-kind="response"]'))
    .find(candidate => candidate.dataset.iface === ifaceName && candidate.dataset.op === opName);
  if (!warningEl || !responseTextarea) return;
  let hasRenderedOnce = false;

  const render = () => {
    const fields = detectPaginationWrapperFields(responseTextarea.value) || [];
    const detectedFields = fields.length > 0
      ? fields
      : (!hasRenderedOnce && Array.isArray(initialFields) ? initialFields : []);
    hasRenderedOnce = true;
    if (!detectedFields.length) {
      warningEl.classList.add('hidden');
      warningEl.innerHTML = '';
      return;
    }

    const fieldList = detectedFields.map(field => `<code>${escapeHtml(field)}</code>`).join(', ');
    warningEl.innerHTML = `
      <strong>Pagination-wrapper guidance</strong>
      <div style="margin-top:6px">
        This response sample looks like pagination metadata rather than a core entity payload.
        Wrapper fields like ${fieldList} should usually not be mapped into the canonical entity.
        Map only the actual entity fields, and consider using a cleaner non-paginated response sample for list operations.
      </div>`;
    warningEl.classList.remove('hidden');
  };

  responseTextarea.addEventListener('input', render);
  render();
}

/* -----------------------------------------------------------------------
   Operation filtering — show only operations whose entity_candidates
   overlap with the currently checked entities.
----------------------------------------------------------------------- */
function syncSelectionViewModelFromDom() {
  const selection = step3PageViewModel.selection;
  const selectedEntityCheckboxes = document.querySelectorAll('.entity-checkbox:checked');
  const selectedOperationCheckboxes = document.querySelectorAll('.op-checkbox:checked');
  const operationEntitySelects = document.querySelectorAll('.op-entity-select');

  selection.selectedEntityNames = Array.from(selectedEntityCheckboxes).map(checkbox => checkbox.value);
  selection.selectedOperationNames = Array.from(selectedOperationCheckboxes).map(checkbox => checkbox.value);

  // Collect BOTH the raw schema name (checkbox value) and its canonical name
  // (data-canonical attribute) for every checked entity.  Operations carry
  // canonical entity_candidates (e.g. "Customer"), while checkboxes submit
  // raw schema names (e.g. "CustomerResponse"), so we need both sets to
  // correctly match merged/canonicalized entities.
  const matchingEntityNames = new Set();
  selectedEntityCheckboxes.forEach(checkbox => {
    matchingEntityNames.add(checkbox.value);
    if (checkbox.dataset.canonical) matchingEntityNames.add(checkbox.dataset.canonical);
  });
  selection.matchingEntityNames = Array.from(matchingEntityNames);

  const entityOperationMap = {};
  selection.selectedEntityNames.forEach(entityName => { entityOperationMap[entityName] = []; });
  operationEntitySelects.forEach(select => {
    const operationName = select.dataset.op;
    const entityName = select.value;
    if (entityName && selection.selectedOperationNames.includes(operationName)) {
      if (!entityOperationMap[entityName]) entityOperationMap[entityName] = [];
      entityOperationMap[entityName].push(operationName);
    }
  });
  selection.entityOperationMap = entityOperationMap;
  return selection;
}

function filterOperationsBySelectedEntities() {
  const selection = syncSelectionViewModelFromDom();
  const matchingEntityNames = new Set(selection.matchingEntityNames);

  const hint = document.getElementById('op-no-entity-hint');
  const rows = document.querySelectorAll('#op-table tr[data-candidates]');

  if (matchingEntityNames.size === 0) {
    if (hint) hint.style.display = '';
    rows.forEach(row => { row.style.display = 'none'; });
    return;
  }

  if (hint) hint.style.display = 'none';

  rows.forEach(row => {
    const candidates = (row.dataset.candidates || '')
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);
    const relevant = candidates.length === 0
      || candidates.some(candidate => matchingEntityNames.has(candidate));
    row.style.display = relevant ? '' : 'none';
  });
}

// Wire entity checkboxes → operation filter
document.addEventListener('DOMContentLoaded', () => {
  initIdentityRoleLens();
  document.querySelectorAll('.entity-checkbox').forEach(cb => {
    cb.addEventListener('change', filterOperationsBySelectedEntities);
  });
  document.querySelectorAll('.op-checkbox, .op-entity-select').forEach(control => {
    control.addEventListener('change', syncSelectionViewModelFromDom);
  });
  // Run once on load to restore filtered state from saved session
  filterOperationsBySelectedEntities();
  const initialInterfaces = step3PageViewModel.phase2.interfaces;
  if (Array.isArray(initialInterfaces) && initialInterfaces.length > 0) {
    renderPhase2(initialInterfaces);
    document.getElementById('phase2').style.display = 'block';
  }
});

/* -----------------------------------------------------------------------
   Phase 1 — entity + operation selection
----------------------------------------------------------------------- */
async function saveSelectionPhase1() {
  const selection = syncSelectionViewModelFromDom();

  if (selection.selectedEntityNames.length === 0) {
    showStatus('save-status', 'Select at least one entity to continue.', 'warn');
    return;
  }

  const data = await postJSON('/entities/save', {
    entities: selection.selectedEntityNames,
    operations: selection.selectedOperationNames,
    entity_op_map: selection.entityOperationMap,
  });
  if (!data.ok) {
    showStatus('save-status', 'Error saving selection.', 'error');
    return;
  }

  showStatus('save-status',
    `Saved ${data.interface_count} upstream interface(s). ` +
    'Provide operation samples below (required for export).', 'success');

  renderPhase2(data.interfaces || []);
  document.getElementById('phase2').style.display = 'block';
  document.getElementById('phase2').scrollIntoView({ behavior: 'smooth' });
}

/* -----------------------------------------------------------------------
   Phase 2 — render per-interface panels with per-operation:
     • request/response JSON textareas
     • field mapping rows (source=API field, target=Entity.field)
----------------------------------------------------------------------- */
function renderPhase2(interfaces) {
  const phase2 = step3PageViewModel.phase2;
  phase2.interfaces = interfaces;
  const container = document.getElementById('interface-panels');
  container.innerHTML = '';

  if (phase2.interfaces.length === 0) {
    container.innerHTML = '<p class="text-muted">No upstream interfaces created. Go back and select entities.</p>';
    return;
  }

  phase2.interfaces.forEach(iface => {
    const edgeContract = iface.edge_contract || null;
    const panel = document.createElement('div');
    panel.className = 'phase2-interface-panel workflow-surface-subsection';
    panel.style.marginBottom = '20px';
    panel.dataset.ifaceName = iface.name;

    let html = edgeContract
      ? `<h4 style="margin-bottom:4px">
          Interface: <code style="font-size:0.85em">${escapeHtml(iface.name)}</code>
          &nbsp;·&nbsp; ${escapeHtml(edgeContract.type_label || iface.type || 'Edge contract')}
        </h4>`
      : `<h4 style="margin-bottom:4px">
          Entity: <strong>${escapeHtml(iface.entity_name)}</strong>
          &nbsp;·&nbsp; Interface: <code style="font-size:0.85em">${escapeHtml(iface.name)}</code>
        </h4>`;

    if (edgeContract) {
      html += renderEdgeContractInterfaceStatus(edgeContract);
    } else if (iface.spec_url) {
      html += `<p class="text-muted text-sm" style="margin-bottom:12px">Spec URL: <code>${escapeHtml(iface.spec_url)}</code></p>`;
    } else if (iface.spec) {
      html += `<p class="text-muted text-sm" style="margin-bottom:12px">Spec file: <code>${escapeHtml(iface.spec)}</code></p>`;
    } else {
      html += `<div class="alert alert-warn" style="margin-bottom:12px">
        ⚠️ No spec or spec_url — go back to Step 2 and provide an OpenAPI URL or upload a file.
        This interface will block export until a spec source is set.
      </div>`;
    }

    // Per-operation panels — built into HTML then we'll hydrate mapping rows via JS after insertion.
    // Edge contracts carry reviewed operation metadata in this payload too, but Step 3's
    // JSON samples and REST-style field mappings apply only to OpenAPI interfaces.
    if (edgeContract) {
      html += `<p class="text-muted text-sm">
        Step 3 does not require OpenAPI operation samples for this edge contract.
        Review contract metadata in Step 2 and downstream/interface details in later wizard steps.
      </p>`;
    } else if (iface.operations && iface.operations.length > 0) {
      html += `<h5 style="margin-bottom:8px">
        Operations
        <span class="text-muted text-sm" style="font-weight:400">
          — at least one sample body per operation is required before export
        </span>
      </h5>`;

      iface.operations.forEach(op => {
        const mappingReviewItems = Array.isArray(op.mapping_review_items)
          ? op.mapping_review_items
          : [];
        const mappingReviewHtml = mappingReviewItems.length > 0
          ? `<div class="alert alert-warn" data-mapping-review="${escapeHtml(op.name)}" style="margin-top:10px">
              <strong>Canonical mapping review required</strong>
              <ul class="text-sm" style="margin:6px 0 0 18px">
                ${mappingReviewItems.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
              </ul>
            </div>`
          : '';
        html += `
        <details class="phase2-operation workflow-surface-row" style="margin-bottom:14px">
          <summary style="cursor:pointer; font-weight:600">${escapeHtml(op.name)}</summary>

          <!-- Sample bodies -->
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px;">
            <div>
              <label class="text-sm" style="display:block; margin-bottom:4px; font-weight:500">
                Request JSON <span class="text-muted">(optional)</span>
              </label>
              <textarea
                data-iface="${escapeHtml(iface.name)}" data-op="${escapeHtml(op.name)}" data-kind="request"
                rows="6" style="width:100%; font-family:monospace; font-size:0.8em;"
                placeholder='{ "customerId": "C-001", "accountType": "CHQ" }'
              >${escapeHtml(op.request_sample_content || '')}</textarea>
            </div>
            <div>
              <label class="text-sm" style="display:block; margin-bottom:4px; font-weight:500">
                Response JSON <span class="text-muted">(optional)</span>
              </label>
              <textarea
                data-iface="${escapeHtml(iface.name)}" data-op="${escapeHtml(op.name)}" data-kind="response"
                rows="6" style="width:100%; font-family:monospace; font-size:0.8em;"
                placeholder='{ "accountId": "ACC-001", "status": "ACTIVE", "balance": 0.00 }'
              >${escapeHtml(op.response_sample_content || '')}</textarea>
            </div>
          </div>

          <div class="pagination-wrapper-guidance hidden alert alert-warn"
               data-iface="${escapeHtml(iface.name)}" data-op="${escapeHtml(op.name)}"
               style="margin-top:10px"></div>

          ${mappingReviewHtml}

          <!-- Per-operation field mappings
               DIRECTION for UPSTREAM mappings:
                 source = field name as it appears in the API request/response JSON
                 target = canonical path, e.g. ${escapeHtml(iface.entity_name)}.fieldName
               AppBuilder validates request and response mappings separately.
               Use "Request Mappings" for fields sent in the request body.
               Use "Response Mappings" for fields received in the response body.
          -->
          <details class="phase2-mappings workflow-surface-detail">
            <summary style="cursor:pointer; font-size:0.9em; font-weight:600">
              Field Mappings
              <span class="text-muted" style="font-weight:400; font-size:0.9em">
                — optional · source = API field name · target = ${escapeHtml(iface.entity_name)}.field
              </span>
            </summary>
            <div style="margin-top:8px; display:grid; grid-template-columns:1fr 1fr; gap:12px;">

              <!-- Request mappings -->
              <div>
                <p class="text-sm" style="font-weight:600; margin-bottom:4px">
                  Request Mappings
                  <span class="text-muted" style="font-weight:400">(fields in the request body)</span>
                </p>
                <table style="width:100%">
                  <thead>
                    <tr>
                      <th style="font-size:0.82em">Source (API field)</th>
                      <th style="font-size:0.82em">Target (Entity.field)</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody class="op-req-mapping-rows" data-iface="${escapeHtml(iface.name)}" data-op="${escapeHtml(op.name)}"></tbody>
                </table>
                <button type="button" class="btn btn-secondary"
                        style="margin-top:6px; font-size:0.82em;"
                        onclick="addMappingRow('op-req-mapping-rows', ${escapeInlineJsArg(iface.name)}, ${escapeInlineJsArg(op.name)}, ${escapeInlineJsArg(iface.entity_name)})">
                  + Add Request Mapping
                </button>
              </div>

              <!-- Response mappings -->
              <div>
                <p class="text-sm" style="font-weight:600; margin-bottom:4px">
                  Response Mappings
                  <span class="text-muted" style="font-weight:400">(fields in the response body)</span>
                </p>
                <table style="width:100%">
                  <thead>
                    <tr>
                      <th style="font-size:0.82em">Source (API field)</th>
                      <th style="font-size:0.82em">Target (Entity.field)</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody class="op-resp-mapping-rows" data-iface="${escapeHtml(iface.name)}" data-op="${escapeHtml(op.name)}"></tbody>
                </table>
                <button type="button" class="btn btn-secondary"
                        style="margin-top:6px; font-size:0.82em;"
                        onclick="addMappingRow('op-resp-mapping-rows', ${escapeInlineJsArg(iface.name)}, ${escapeInlineJsArg(op.name)}, ${escapeInlineJsArg(iface.entity_name)})">
                  + Add Response Mapping
                </button>
              </div>

            </div>
          </details>
        </details>`;
      });
    } else {
      html += `<p class="text-muted text-sm">No operations assigned to this entity. Go back and assign operations above.</p>`;
    }

    panel.innerHTML = html;
    container.appendChild(panel);

    // After DOM insertion, hydrate existing mapping rows from saved session data
    iface.operations.forEach(op => {
      (op.request_mappings || []).forEach(m =>
        addMappingRow('op-req-mapping-rows', iface.name, op.name, iface.entity_name, m.source, m.target)
      );
      (op.response_mappings || []).forEach(m =>
        addMappingRow('op-resp-mapping-rows', iface.name, op.name, iface.entity_name, m.source, m.target)
      );
      refreshPaginationWrapperGuidance(panel, iface.name, op.name, op.pagination_wrapper_fields || []);
    });
  });
}

function renderEdgeContractInterfaceStatus(edgeContract) {
  const status = edgeContract.status || 'Unknown';
  const badgeClass = status === 'Ready to export' ? 'confirmed' : (status === 'Reference only' ? 'draft' : 'warning');
  const entityDisplay = edgeContract.entity_display || 'No canonical entity linked';
  const summary = edgeContract.mapping_summary || 'Reviewed edge-contract metadata is saved in Studio.';
  const detailRows = Array.isArray(edgeContract.details) ? edgeContract.details : [];
  const missingRows = Array.isArray(edgeContract.required_missing) ? edgeContract.required_missing : [];
  const warningRows = Array.isArray(edgeContract.warnings) ? edgeContract.warnings : [];
  let html = `<div class="alert alert-info" style="margin-bottom:12px">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <strong>Edge-contract readiness</strong>
      <span class="badge badge-${badgeClass}">${escapeHtml(status)}</span>
      <span class="text-muted text-sm">Canonical link: <strong>${escapeHtml(entityDisplay)}</strong></span>
    </div>
    <p class="text-sm" style="margin:6px 0 0">${escapeHtml(summary)}</p>`;
  if (detailRows.length > 0) {
    html += `<ul class="text-sm" style="margin:8px 0 0 18px">
      ${detailRows.map(row => `<li>${escapeHtml(row)}</li>`).join('')}
    </ul>`;
  }
  if (missingRows.length > 0) {
    html += `<p class="text-sm" style="margin:8px 0 0"><strong>Missing:</strong> ${escapeHtml(missingRows.join('; '))}</p>`;
  } else if (warningRows.length > 0) {
    html += `<p class="text-sm text-muted" style="margin:8px 0 0">${escapeHtml(warningRows[0])}</p>`;
  }
  html += `</div>`;
  return html;
}

function addMappingRow(rowClass, ifaceName, opName, entityName, source, target) {
  const tbody = Array.from(document.querySelectorAll(`.${rowClass}`))
    .find(candidate => candidate.dataset.iface === ifaceName && candidate.dataset.op === opName);
  if (!tbody) return;
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" placeholder="apiFieldName"
               class="mapping-source" style="width:100%"
               value="${escapeHtml(source || '')}"></td>
    <td><input type="text" placeholder="${escapeHtml(entityName)}.fieldName"
               class="mapping-target" style="width:100%"
               value="${escapeHtml(target || '')}"></td>
    <td><button type="button" class="btn btn-secondary" style="font-size:0.8em;"
                onclick="this.closest('tr').remove()">✕</button></td>`;
  tbody.appendChild(tr);
}

/* -----------------------------------------------------------------------
   Phase 2 save — samples + per-operation mappings → then redirect
   P1 fix: operation_mappings entries now use the OPERATION name as `name`,
           not the interface name. AppBuilder validates mapping op names
           against declared manifest operations.
   P2 fix: mapping source = API field name, target = Entity.field.
----------------------------------------------------------------------- */
async function saveSamplesAndContinue() {
  const panels = document.querySelectorAll('#interface-panels [data-iface-name]');

  for (const panel of panels) {
    const ifaceName = panel.dataset.ifaceName;

    // ── Collect samples per operation ─────────────────────────────────────
    const sampleTextareas = panel.querySelectorAll('textarea[data-iface]');
    const opsMap = {};
    sampleTextareas.forEach(ta => {
      const op   = ta.dataset.op;
      const kind = ta.dataset.kind;
      const val  = ta.value.trim();
      if (!opsMap[op]) opsMap[op] = { name: op, request_sample_content: null, response_sample_content: null };
      if (kind === 'request'  && val) opsMap[op].request_sample_content  = val;
      if (kind === 'response' && val) opsMap[op].response_sample_content = val;
    });

    const sampleRes = await postJSON('/mappings/upstream/samples/save', {
      interface_name: ifaceName,
      operations: Object.values(opsMap),
    });
    if (!sampleRes.ok) {
      showStatus('phase2-status', `Error saving samples for ${ifaceName}.`, 'error');
      return;
    }

    // ── Collect per-operation mappings ─────────────────────────────────────
    // Each operation gets one entry with name = opName (not ifaceName).
    // We collect request_mappings and response_mappings separately so
    // AppBuilder can validate each kind independently.
    //
    // We ALWAYS POST — even with empty lists — so that stale mapping entries
    // from a previous op selection are cleared server-side (reconciled in
    // entities.py, but this flush covers any that survive a re-save).
    const opNames = new Set();
    panel.querySelectorAll('.op-req-mapping-rows[data-iface], .op-resp-mapping-rows[data-iface]')
      .forEach(tb => opNames.add(tb.dataset.op));

    const operationMappings = [];
    opNames.forEach(opName => {
      const reqContainer = Array.from(panel.querySelectorAll('.op-req-mapping-rows'))
        .find(candidate => candidate.dataset.iface === ifaceName && candidate.dataset.op === opName);
      const respContainer = Array.from(panel.querySelectorAll('.op-resp-mapping-rows'))
        .find(candidate => candidate.dataset.iface === ifaceName && candidate.dataset.op === opName);
      const reqRows = reqContainer?.querySelectorAll('tr') || [];
      const respRows = respContainer?.querySelectorAll('tr') || [];

      const requestMappings = [];
      reqRows.forEach(row => {
        const src = row.querySelector('.mapping-source')?.value.trim();
        const tgt = row.querySelector('.mapping-target')?.value.trim();
        if (src && tgt) requestMappings.push({ source: src, target: tgt });
      });

      const responseMappings = [];
      respRows.forEach(row => {
        const src = row.querySelector('.mapping-source')?.value.trim();
        const tgt = row.querySelector('.mapping-target')?.value.trim();
        if (src && tgt) responseMappings.push({ source: src, target: tgt });
      });

      // Include entry for every operation (even with empty maps) so the
      // server always has the full current state and can clear stale entries.
      operationMappings.push({
        name: opName,
        request_mappings: requestMappings,
        response_mappings: responseMappings,
      });
    });

    // Always POST — clears stale entries even when user removes all rows
    const mapRes = await postJSON('/mappings/upstream/save', {
      interface_name: ifaceName,
      operation_mappings: operationMappings,
    });
    if (!mapRes.ok) {
      // Surface field-level validation errors so users fix them before export
      if (mapRes.errors && mapRes.errors.length > 0) {
        const detail = mapRes.errors.join('\n');
        showStatus('phase2-status',
          `Mapping validation failed for ${ifaceName}:\n${detail}`, 'error');
      } else {
        showStatus('phase2-status', `Error saving mappings for ${ifaceName}.`, 'error');
      }
      return;
    }
  }

  const reviewResult = await saveSuggestionReview({ silentIfEmpty: true, showSuccess: false });
  if (!reviewResult.ok) {
    showStatus(
      'phase2-status',
      reviewResult.warning || reviewResult.message || 'Samples and mappings saved, but suggestion review could not be fully saved.',
      reviewResult.degraded || reviewResult.partial_failure ? 'warn' : 'error'
    );
    return;
  }

  showStatus('phase2-status', 'Samples, mappings, and suggestion review saved. Redirecting to Step 4…', 'success');
  setTimeout(() => location.href = '/handoffs', 700);
}

function skipSamples() {
  location.href = '/handoffs';
}
