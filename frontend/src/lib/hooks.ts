import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Application, type ApplicationFields, type StatusDef } from './api'

const EMPTY: Application[] = []

export function useApplications() {
  const q = useQuery({ queryKey: ['applications'], queryFn: api.listApplications })
  return { ...q, data: q.data ?? EMPTY }
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: api.getSettings, staleTime: Infinity })
}

/** Status name -> definition, with a fallback for statuses no longer in settings. */
export function useStatusMap() {
  const { data } = useSettings()
  return useMemo(() => {
    const map = new Map<string, StatusDef>((data?.statuses ?? []).map((s) => [s.name, s]))
    return (name: string): StatusDef => map.get(name) ?? { name, kind: 'applied', color: 'gray' }
  }, [data])
}

function useInvalidate() {
  const qc = useQueryClient()
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['applications'] }), qc.invalidateQueries({ queryKey: ['dashboard'] })])
}

export function useUpdateApplication() {
  const qc = useQueryClient()
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ApplicationFields> & { flags?: string[] } }) =>
      api.updateApplication(id, data),
    onSuccess: (updated) => {
      qc.setQueryData<Application[]>(['applications'], (old) => old?.map((a) => (a.id === updated.id ? updated : a)))
      qc.invalidateQueries({ queryKey: ['history', updated.id] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: invalidate,
  })
}

export function useCreateApplication() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: api.createApplication, onSuccess: invalidate })
}

export function useDeleteApplications() {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (ids: number[]) => api.bulkDelete(ids), onSuccess: invalidate })
}

export function useBulkStatus() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ ids, status }: { ids: number[]; status: string }) => api.bulkStatus(ids, status),
    onSuccess: invalidate,
  })
}

/** Change one record's status with an optimistic cache update (board drag-and-drop, quick actions). */
export function useQuickUpdate() {
  const qc = useQueryClient()
  const update = useUpdateApplication()
  return {
    ...update,
    mutate: (id: number, data: Partial<ApplicationFields>) => {
      qc.setQueryData<Application[]>(['applications'], (old) => old?.map((a) => (a.id === id ? { ...a, ...data } : a)))
      update.mutate({ id, data })
    },
  }
}
