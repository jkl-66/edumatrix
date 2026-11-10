// Generation jobs and saved personal bundles expose the same artifact binding.
export function bundleResourceReference(item) {
  const resource = item?.resource
  if (!resource || item.state !== 'succeeded') return null
  const resourceId = resource.resource_id
  const resourceVersionId = resource.version?.id
  if (!resourceId || !resourceVersionId) return null
  return { resourceId, resourceVersionId }
}

export function bundleResourceReferences(items = []) {
  return items.map(bundleResourceReference).filter(Boolean)
}
