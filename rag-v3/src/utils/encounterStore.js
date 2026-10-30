// Browser-side list of encounters (id + secret access token + label). Lives in sessionStorage (cleared when the tab
// closes) and NEVER holds chat text — messages and context notes are always fetched from the backend.
import { SS_ENCOUNTERS_KEY } from './constants.js'

export function loadEncounters(storage = globalThis.sessionStorage, key = SS_ENCOUNTERS_KEY) {
  try {
    const arr = JSON.parse(storage?.getItem(key) ?? '[]')
    return Array.isArray(arr)
      ? arr.filter(e => e && typeof e.id === 'string' && typeof e.token === 'string').map(e => ({
          id: e.id, token: e.token, label: String(e.label ?? ''), createdAt: Number(e.createdAt) || 0 }))
      : []
  } catch { return [] }
}

export function saveEncounters(list, storage = globalThis.sessionStorage, key = SS_ENCOUNTERS_KEY) {
  try { storage?.setItem(key, JSON.stringify(list.map(({ id, token, label, createdAt }) => ({ id, token, label, createdAt })))) }
  catch { /* storage unavailable (private mode): encounters then live for this page only */ }
}

export function addEncounter(list, enc) { return [enc, ...list.filter(e => e.id !== enc.id)] }
export function removeEncounter(list, id) { return list.filter(e => e.id !== id) }
