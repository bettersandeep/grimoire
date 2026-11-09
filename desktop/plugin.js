import { ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, host, queryClient, useQuery, useMutation, useValue } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'grimoire'
let pluginCtx

const PATHS = [/^\/summary$/, /^\/queries(\?dataset=[\w-]+)?$/, /^\/queries\/q\d+\/explain$/, /^\/settings$/,
  /^\/merges\/(approve|reject)$/, /^\/datasets\/[\w-]+\/forget$/]

export function assertPath(path) {
  if (!PATHS.some((re) => re.test(path))) throw new Error('Unsupported Grimoire path')
  return path
}

export function errorText(error) {
  const message = error?.detail || error?.error?.message || error?.message || String(error)
  try {
    const parsed = JSON.parse(message)
    return parsed?.detail || parsed?.error?.message || message
  } catch {
    return message
  }
}

async function request(path, options = {}) {
  assertPath(path)
  const result = await pluginCtx.rest(path, { timeoutMs: 15000, ...options })
  if (result?.error || result?.detail) throw new Error(errorText(result))
  return result
}

function useData(path) {
  const profile = useValue(host.state.profile)
  const connectionId = useValue(host.state.connectionId)
  return useQuery({ queryKey: [ID, profile, connectionId, path], queryFn: () => request(path), refetchInterval: 5000, retry: false })
}

function useAction() {
  return useMutation({
    mutationFn: ({ path, body }) => request(path, { method: 'POST', body: body || {} }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [ID] }),
    onError: (error) => host.notify({ kind: 'error', message: errorText(error) })
  })
}

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
export function fmt(v) {
  if (v === null || v === undefined) return ''
  if (isNum(v)) return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 })
  const t = String(v)
  return /^\d{4}-\d{2}-\d{2}[T ]00:00:00$/.test(t) ? t.slice(0, 10) : t  // a date stored as a timestamp
}

/** [label index, value index] for a bar chart, or null (same rule as the chat chart). */
export function chartColumns(columns, rows) {
  if (!rows || rows.length < 2) return null
  const value = columns.findIndex((_, i) => i > 0 && rows.every((r) => isNum(r[i]) || r[i] === null) && rows.some((r) => isNum(r[i])))
  if (value < 0) return null
  const label = columns.findIndex((_, i) => i !== value && !rows.every((r) => isNum(r[i])))
  return [label < 0 ? 0 : label, value]
}

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(seconds * 1000).toISOString().slice(0, 10)
}

// The Grimoire icon: the enchanter Merlin (pen drawing by Howard Pyle, 1903, public domain), 64 px.
const ICON = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAQAElEQVR4nIx7CZAc53Xe1z33vbP3gQV2FxdxkaAAEiTBK+IpyhIpOZIjWZYl2hWlrMQuO5ZixU6KiqwjqbJKdqXKdpwKpZLsJEocy5IZkaJESiIJ4iBAgLj3wAJ738ecO2f7e697ZnoWkOTZmu2Znj7+d33ve+//24tf/DJiwaGjpomnDMO417BwmwWjlfv9/El+Bvfzv8mt85b9ztbe3/heOx7Or7rL0ts4t7Oc/9xaVv2bvceCvbtqf66/9ZiiZVkr/HCFv75ZRfn/r6YvveE64NbC/ZzfzJbgwK9bHuNzHOhOOEO2LKN+qv7VhTYdIW2BDcPTrBj9vSa0UVfGzcNoVoB+cm3tv6qjHDnmZmVYdYVVR6pW9csr6Utfx89QxC0VEA9s2WGY3m9SgHtgOIdYzQM26sKaTZ9NFdxRhnxGwyvq3lHzilve3rLldlldLA5nW7e+s7VcWzQpwnIr8XihWP21VOHS6C9UQDww8ITpwbf5U9w+wnCErx3utrqHAteU4NG3qcJzC09dIaIMs+YhhlsRt1BA3cqO5ZsErdaVANdna7NyUL1JCTw3Va3iwyvZiy/9TAVQ+Cc5tu9ykL6G8A3B3cKrgKanvrWFd7awt/q72wv07YXXE+B+H0z+bstcRbVaRqVadFnbahK4WQEVVPmuKcL+bG1SUEMRNSVULcGJ6tMr2Usv3qSAWKB3t2n63qLwUThxKgaoA1ctho2a1WXrbQhd+2x6XZ898HvjCAWSCPgT/BxT4RvubzRZQgZaqRRRLGdQKKawUVxDqZSxFYRmwS3d1r679okauMUmb3CFTaZQLB9OF65elft6nftTJv83OYpobVCWy/I14KrFtwioQteFdd7Od58vilioB+FQJ3yeMLcGdu+wsGOoit6eCtrbLMSiFpVi37xQNJDOGFhaNjAz68XYeCuGRzuQywPlSh65whKy+XkUS1mYKnSZ4zPpNXZIVfVz2f5crXAMIrLhCAxVgipYwtOqRv1+7zdRwD3yg0obCw580jSt/1GztuUowahb3my2uulVV/bUhfbpNuhvRSK6DeFgOxJxAw/ea+Gew1XE4msYGV+gEBYisVbe1U9hLPgDIXVbn8fE2uoyDKsAq5xHPOrFzsFOpNNJnDjlxevHvVhPWcgXVpHKTlBh66oEfVdrCnFvK67QqdhZo+YF6kncU60+y1B4XiWOh7ZdpvZ2227YsLo7tZmmp8nKttA+ePj2eSNoje9EhBYf6DfwgV+qYv/eDeTKfvzZX30fZ86No1gsIkCTV4hEosxoJISNQpEDsdDWGuPvZeQ3Cihwn+ExqBQv+rtbcPe7tuGJh/bi+o1W/P0LftyYNJDdWMJa+hpK5RzPLzmKKKvgthJsxbgxQz/XQsLSb1eX0xf2eGLBrfebpvGZekxaNvjVUVuQ3jRdlqfQ8vb49R2P9KOz9QD6uhP4V5+08OFfLmAxvYKRyQ3MLRVouRx27tiGrs4k+rZ0IZPN093zSKXzPN/D8AgwAE0sr6yri24UCmiJx/S8pdU0zg/PI18JI5WZwkc+6MG+3SHcmIhxPF0qsISIUcMSF6QbNYJVy+K1lKhiamC0BzwdL3tCvsSnKejROtpvIi+mE+uGKsC2uAju9YTQ0bIPLbEBPPWoB5/9XZ4eqOLY2wsUfANPvvcJ7N2/D/fffw/uvecQ9u3bhWKhhNaWCPbt3Y6xa9MEOQJeqUzM8NIzLKyuZ9XTAn6vKkWG8/i7j+DlV0/h2FsjeOknV1GyFvC7n2qnMGHMzrSr9wlgqu8azWmtSQnubR3drCVPwJf8jzxwW/1Ud5ozGpa3hfdz60fAG0VX251ob23DZ/414/zeMhazcaxnCTbU7pPveRSvvX4CP3jpVYyOXENqPYUdu7Zj/4E9OHLkEOKxKDEiQHeeo9BpHUo+X2AIFLk/QqtWGQolPHjf7QyfEWToMRIyItCFKzP43o/O46O/3I6H7o3j4qUEx5VEobSubt/QgOUowXJxQGsTpbGqVEDiS7R5tI74Zs3ypmN1jwrvlZj3+BD0xdHddghbt0Tx+X9XQaiFMVlJYmZqDtvp6qur6/jyf/5LLC0s4cBtW3HbbYPI5bI4feoMTp8+h3PnLiASieApKinILFBm7K+spBAM+bHOsIiEiRNUQFdHEuVyVRVko3sVy6sZZo8Q/H4f/tkjj9AAZTz6QAkXLkV5TpumTcECOELXYA+3+O9s/eIBXzQ0HboYnkNqbPd33J6W96vw78LQtgi+8O8tbBDNA/E+XBsbQ0uyBZl0Bq2tLZibm8fB/dsRb4mhd0s3Bx1GcWMDPT0dCnjHT7yDY2+exqOPPkCw3EmeYGBicgFer7g/lU0j7N61DSNjk8jmCqoQMY+H2SLg9+P3f+fj2D7Qh2KV42K4PP5gDucvBlEqihJWmOkqmwUF6rRY0qFVcwJRQMsXDJfr2/TWyfGm1wY8RfoQulvfha19UfzR7xcxvVpBxYgwfv1oaSHZCYXg4+CPn3wHCwsrFDRBa4awtpbC+noGs7OL6OvvY4oL4fBdB9XVv/Wt71C4Eo4evQtDAz108yDGb8woOPZRWRIiIryMfaNQRl9vBz71yafR3dWGcqmEzs5OmD6CIr3vmScMnDlLJZRayBuWFfntmG+qCWDBXUEKL/O1PNdU1Rk14PM4CrDRvjN5AB2M+T/+Q0JHKIF8yUSYrlwplzE1PcuBlrG+tkbrL/E8xjQHXCiWlA2mM1kMDvbBQ2VFImEqLYRdt+3B0fsOUbFefOuvv8N9Pjz6yH3Ys3srQ2JdrT0/vwQPf98gHtx/z3586fO/zbExbba1IZfNKYAuzM6hTDrT2duDe+5Yx7ETEcoa4v2XnZwPNFWLLkXIn6OAZtf3mDal9Wjc+0luthLtB/HZf0OVBkuK8p3dPdggVfNygDZm0J8CAQwPX9cYFYHbO9roBUEU8hv0grTGdDIZo6f4Na7DEYJpdxc62qJ03wJe/MEb2Nrfy7AYxDy9aHqaYUFvCBIsnnzsXnR3tpMcpeFl1pB0Go1FkGDoSegsr2Y1Jb5rn4GTb8WplCK9IYvN9YAbGVBTgGk0PMDj8HmPvn0IkNZ2Jg/ifU94cfBgDlagGyOjN5AlModDPlppXj0hR2VsbOQwSw/o7+vA8vI6QuEwBTDIBCP6vUwv6SC4LczNqhJCDBHxtJ7eXmzkc+jpTGAtlcGJty5gx+AWtLfHMTG9qEOd5vbhhw4rsZGw6+nuQJZekMvliBM59PX1kCVWsHeXF3luJ6cYChuLTK+lBgN0eUFtnyfoSz7XcH3TzvmO8AJ8HS17saWnBb/36SpOXlpX+uqlu/b3d+uFRIhQMIz5uTnGZCsOH76TggLvfuQBesEA/uy/fovxv0Dl7SUPKKKrq13xIM9BG0aVITPH2A9jy9ZtmJiYxrZt3SRNrRglAF65fA2PP3Yfrg5PaIg99eRRWtvHEFlFIpEg7gQ1dMQLBRwFg4R8PXR3Ca8f8zOV+phal+vC242URqUolJhEqPU55fqmWa/mRHhB/2CgFW2J3fitZz1I9iRgkHSIy05OTFLoIObml2nRVo3XMl24WKyS7fXR6sArrxzD1/70G1ghCD5w9A4sLy0j0ZJANBpSjpNO55BJpRGLhbC6sowk8SXZ1kocWSZfOIBkXKzchqsjEzh05x5cvnIdz7zv3ZicnMbgwDYsLy7Rq1aJDxsaJqtraYIxOQEpdI7eNNBTxemzcc0K5UrBFfWubpKEQNBve0DN+iJ4jee30/q7BuP46IctTK94sKV/Ky5dvMJ01kUyE0aAFiiWqpr2igQ8QfQUXfjylVH87XdepaeYFKKd3CCD23YPon9LLyamZukFncSCBC1nag1QIpCOjl4jIEpl5yHCF+n+7ejt7cS2Le2Iki7nSJSEQcZIovz+AK0fQCQaQxuvI/wkmYxjcXFVLZsrmLhjj4W3TptMzT4NhXpdoN5QqSuBIdBqh0Ct2DHs+A8w54v1f/NjJoKJMFbWN2ipVXh5cxno+PgU5unKW/t7KKgHFV68o70Vc9x39p0RXBmdUDZ3+77t2HfbNtx+xwG6K3RfKBhg/GYZMu3MFGW1moDo3Mycun+GQGfHuo8hF1RQLTLtvfD91yish+V0jPvExTewsLSi50oNa5FOC9h2MswCwSjiwRS9IKoKqFYLjWaJowhRAhXQ9pxZ6+U5rE88IUnU7yaK/8tPGEiVE2htSyoYCdlZWVlTBxoY2GqnKVrHL/xdKC1j+7HHHiby55ge59GSiOLhB48oGJ45fQFbtvRQYLINjtrnC2psi1KEOXYx92eYMk2vR/O8RzxEFEZrC0EKBXz4f9/7MV57422SMq96oShMqsiRkXFcG7+hwBiPx2Gx8bJnIIeXXzGZEisMldW69WtYUMcAw2wQH9MhPuL+73kkgB23hTC7kMPais21u+n+U5MzCjp9fV0a23IhGXCAadBPb3j77EUqr5WCFTA6Pq2k6Kc/PYVpeoeAXJjZQQUkmoeZJsUqobCQmKrS2ASrwVd/fEKJTzgcEEfV41Y5hqFtXXjn4jguXbmGE2SUGxt5KrHCMa5g+/YBDS0pu4N8l0t5zQjXrgWQzs3YwmvJ3AgHT8hve4BR7+oI+CXREh3Es79qIke6GY21KPiIi0v85fN5tLUnCWQZzQLC1wWIVlbXGMs3NA7LjOv1VFY9R6jt4UP7bUK0tYuxG1VLiSd5TFZxDIECrylKuXBxVC0eogCS4iTmfVSqpNEeYsICyVEbuYRQ7l/9yFO4i6yyo7MNO4e28vyykiOh3ktLAn4G+jsq+PEbASVG5eqG1hR2g8RWgl1z1nv59jvEzk4kbGDXLj/r8CIuXbpCrp9gvs2TsBQ1dgQPIpGAsjVxzxhJibCzZEuUgmVIgTN47JGj6Otq1QJm67ZeveEaS14Bvm5mE4nv4yfOK5uUTrI0TbpIc7NUVBs9KEyskOJKBIvz+pOT8xgiP+jv66TlCwTGvGaBlFSU6sUGwbNVhUww9EbGZhimlrbkgv4WNCZx7EpA/jxh8QCz4QHC/hKs8Q/dHmMtz04N6+42XvQ6XTlDAWdm5pn6OpThpcjxd7HMXaXlhQiFWbIKFe6hcLF4lKi8TGK0jL17hjjgEq8bonv61LKrVNDhuw9jamaBCig59YSfyksr+udZBAm+LC2tqjB2T9JgJyinxyVZaJ0/P8K020OcSahh4vEEPa+kfKNYrLAEH0Ius8i07cPMfIUKW3Q1Ue22mYaA3dOv9fh8aGN766H7/IglsvBHJDensaWvm7k6oaVtR0c7y9eAkidpaQk2SBk9M7PIev8g3XWNjc1pCtLFeA4pYemkJ1QJeJIupeszcWOa4V7BoUO3Y2jHTkV8ocod7S08ZkNRP0ElFukdM1TSwMAWKs+ryg4EwuwgLdPaLUzLowqcESpfSuE2pk8PyZKEaXt7G32b5fZiCVeGTaSzUw4OlOutMiqgjnQ+LwAAEABJREFU3eYBThqUwqctvgtPvNuD1MYarZrQjk2JuTkajRDk/KptiW0RXpuavKEQIy+B8ZVX3iToTOHA/t30hCRuP3iA8V3Q/p8I2MnWmIdnyTUFQ9ZWV5SExQl8re0dFC5I74kjn8lQEI/eIxqjJ7K4knTY3kahL41wLHHtEMdJs29MzDI8ZrRpssqCTAwkRhGiNDfL/WSvJ8/4sJ6bUCUpEDqA6AkF2p8zXfzf72OBEdmG9z9pstlBJsUUks1ltUtT5TueiDGmmL4oTJaDDAZtUpIm4MXjYezft5MDDmIPGyHCE3LZFMvgfvzwh28wBXaiSov6BeAYwwEWOSaVN3x1DDGi/eLCPMNqnddk6c36IJFsxbbBIWV4mfS6KkPKbskIVbq64M7s7BKzUbvSYUnFkpolLUYJtCV60fzCMnrawnj1NZKiPMtrAqGlDVPbC2rzAvWXx5kUokHYL29VyxXIrMTtJM1duXKFAw/Tkm1KSiL0ipmpGQ4mxgZIAufZ8ZmfW9Quj6RKL622vraOJ598mPGY0rQVZxXYylCQeG4jg5tl1Xfx8igpbh8VxqZpOqVguY/Nkrw/jWg8icHtu9h4GVH8ENcWIK44xdUqsaibIbaWyjtcJa2psMr0uLqWw76tdvWn8xnuNokh8L/5pXN5LG3ZrirRytKIyHCg16/f0Mpvx44BpiiPVmQJekORfTzh8XmWvJM3JkiX+7Bn7w5cvDimcSioK3ixQFdcT2fVSkKfpXCRGkLcemioj6Aa0FiWYyQrCOCtkO9PTU3xuqP0Jp5P7zCI9MIYJUykbBd8KdDiKXpgC8cj2UEaJYI1kj7FQLUJGMOZ7WpowLqFAlyvq1dH6dopRWNhbmu0pFBX0RBDWPO+oEAmk0aQAoQ1v+fVZQ8x77+L7wlad4WxKJaSvoB0JX1kgpKBJZ8HQ2HOBi0qWRJCJeRHPEkqS7/wAQq4ns5pTLexWFpk2g0Sb1Jra+riJ05fUuZ4N5utwg1EAcVSQUPiwsVhzU7Nr+aukLfRLnb6ZTqvBki6lx5enEgsKUw4dn9/Fy9Y4I1alb4K7ZX+cSuBafz6lF5GymQRKEqO8A8v/FgLlN7OFuLAXhhT85oBpOqTCRDqQTvGcl6Asb3Coqm/P6bMTqpFwYI8KbUoR/AibIaVwMxQqW+SP0iKnSQGiBV7ujvZgN1Fl1/XTNHOrtEQydHlyyM0miO2yNYwvyrc29w7ZVxZJf3ESpUcIIcwOz9zc9eZ7wdVUfncMkFmQ+NU+nWS78X9+5gmr7IKXJhfUZ5+/NxVeo2pgCUelKb7StgI+RGWWOEtxZJRMr344qKmVAkFUUySXR6xuHibzxdgpkjRs+bUrc8x99+YmNOMIiCms0kMwy985Xk8cP9B1h2H0d/bjbNnWXewu5SIEaDTtoHt5oirN8D/3sZqCssBlg39zPBDjDTyzOmzuPPwQQUyn4YCFPmnJtPahZH0eePGdW11DZGL51jlHTt+ni2qdewjAZKSV1C3Ui4wVTLF0ntmZmcJUiEeW1JhO5i7paDioZAIO3nyrH0eFXxjiiHEGSIpmS1q7drEjDJEwRLpOVbYfZGMIqzupR+dVOX8xiee0evKNffsHsDEsN0PUNkspzVm2VPwZs3yzpISdRPprU3OWOjldJcwrRUWPGnh+5KXCZJp1vw7dgzRLX3M+dcVsKRGEEEFK7JU+cEDO7UFLoOUclfIiU5c8B5BZhNBcClpV1kPTNKlpXCSwX/3uz9S+ruynNJminiXUOSlpXWMM99LkZVIRJQjTNP9ZTJFSS3vK1T4/OVxfP5Lf0kDMvToCSF/lWzTnmWuT5q62mPeeo+M7yintHf3P41YpA9zUxFcetuHVN6j1hC+PUNEDTJW5fhLVEqSPEGLI2JBZtmkh3jorutoDe7GwBZpOF4iITIV1KROkGpPiiAhVMIrhAIfe+20cnppePSwDmghxd2/f6f2HMeuTWB4bEp5Ro6KEMKU1wnVCq6MTGnGEAULP5DOsWQVn5In4Gt//r/xGx/L4plHt+PadYPAmHHNGDeW1ngtNBqEkVAXDu581sYJQsGZE/i5r9mf89v4yBsY3AMsLa7RWwY5eKao4iIBNKk1RTG3wTi9iPOXRrWmP3LXPk2ra6TdIugsucT0zBIbLt3wU6g9nCiZItWeZHNUaPYcrys1gcwh+Nh5klltqSDXqJRw2FIPev6vX8BH3vvbYDLjvdftThCq9fi3iZDOmNoekM5N4+3h/86LBnSe/8F7yQl6W/C6P4J/6uvI9XGd8e3sWyRr5LR5a1xBUAqUGTZIJL29/topLJEoTbC6u/OOXUTvAYZLi7q71Plnzl5RgJTStoNeJhlBQPLUmWEWNcvqPcIfpB0mJbeArmwtrUssLbSCLLo622MYG6PX5Qx6yIq90sS1dkBk99YXGBm2As6M/BXBKMC5+QdwZyHG4iaJ141u7f+V1N2qGrumxpxdQ0iqsjs4XuxvH1UWJj3/5eWcplEptoTFRR3qeu36jLp0B+uC/fuGtDw+fvICU21Kp8KkZRagUFvICeSa4tZvnR3WlCeZR0iTMNQVekuARdQCewVSZVq1NYSWqSHx4N2DePOUQQBlqJRT9poBy+kKOVhQ9wC4V1TwLbz5J8ci+NivpPE7637kZ8nq2LwwnSVwBaZCEVL6cdIRlgaEIXN3pLbSJImSqRVZq2cy7CaRtBRozUHW8QJ0sj5AUtrOHS2cY5jUTvXFS2Msmwd14H297ToPIPEtCrlwZZwAOKdMrkIhVpwwidD9SwRTUYhMw4nl42yGyHlSrj/z+B34D18EsvkF3qPcWC3iAkKzthyt1jWtOm6Syc6QY1dx4lSFEyMeBapKRRYgQbs0eZKj5eVlLWxusJ8/xT5BiqlSQDIWpztnWemlcpoyxWrSPpN4PUtLShkr1eMCSVKKCppW4iSMcEm/ixKkzhBWefbCKNtqM4rVZRIkUUIrgVL6gToFly/ynDzTblq/ywoUCYnH7r+NnhanUsSYM019gKpr5Zm3viRNw0DAwV5jUyyntZv6t9/rxp0H2cru7NabiRuvLK/oNLbE27WxcRVkK1mi6fE6qFxRgjLDOcOdOwfVPVeZ0t4hiRGLdZEJygKJRWYMcUChrzID1NfTTiyIK16cv3QNZ8+PkjBZmupKZZvFSTjIyhHhAVXFAjZHqbwCQ3CD9y47x/3aBw/jvz1vqAzFUtpeRgN3M8ROg2atP24rwRUjFELW4YxPVNjmpteXVnVCQyYkJOdK3Iq1s0TdBK0h3Lub01UCXpIWhcb2UCBhjeWypQXO+PVZAqRfFSIpS6wqVhfh+xnvPo/0/lJ44eUTOPn2sLJCoeHqddGQKjzDdCknptN5eyFFsaSNEgkJEV485OnHb2eztpMzzWzBZcapxHJjUVVdRjv9m415s+qm9XdlbSULFnz9b9h48Oe1zJSBX7s2qTFWKuRJX7dg5+7tiuLS8REiVGXBM03rC7npZV0vHd9t7OgssVMkYTQ3v2pPoHJKXMpYUUqGabFEFxeUn5ha1I6QTIIK+ZJOsyC8nCPgKNcQT5DYF0NmsgV1f2GIQSrj937zMXzjf0LHvlFc1fhvXk/YmCs03USo4QV2x0SUsLw+jPnFIr79dwaGekBwi+lkiABdgAMTLJCZXWlOymSodJClvVWkcmQliKQvmd0dJ/JLDbBGQjXGSZWOthZleEKvo3IeuzlvvnUZpzmpIiCnrbZa3MPQEJDJDzvz2M1NqTVEEWJ5r8cmSV/5g6fx4stR8gRmidRIfRVZow3WmBRBHQTrk4UNEKy5TKmcwXLqKv7h5QrGhpnqyqvqBVImS8wLyAlnD8qaPw5W+3lUiAggHdoOToOJUsavz/FYH621oXX7MDFgenZZBZOe/g9/eobcYM1OStqdhrJDMYp81hDgb9JiF54h8wUCfjnig+CALLD6rY8/hN62fQyhKlbSwzr2quUooGqHdX0prvPn9APqC4obWqo2lJDKTtJFZ/HVP6/I3BZWFyY11n3k9IUNOxbFUiVupRQt5LPatZH+wI3xMWaHVYyNjjPeV5S+CmjKChEpg8+xcfIO+fsCub50coVniJVFEfLZ9gRLl9WJtUVgLWJkfQE9K0ZPFEUcPbwdH3rP/fjqX1Q51jkds1R/lboxG6mv7gV8efze2HO2EmoPMjjLpZw5Ajh9dMEDj9FGdA7gox+IoaVdUD+o1pbOj3iC8HihpEtLKc4it5PPp9kxyisQnjp1gQrzsZubUhcfYWoTy29QIPEKP2NXhBXvkqUyslhHls7ZC6Qsu+FJK8sEjOCF8nh6YJqp8uF7d+Mrn/0QvvgnHswsrGN+5RzPLaj1Nf/XOEBtlTlcCySogM8BdjqsrQlG03MMzj5JR5xqrpY7WZN78dARDsYfJMhYKrjEoYCd3x9WwhSiu4tF5RITrOJe+clpkqINreBWSFikvJWcLSAnTVYBMKG+0iNcI62VzwK04l1aZFF4GYecJ7EvhCdNxR2+fSv+y+f+Bb78NS+uT2Uxt3xGmZ8d+64WuAvo7TUC+ipQAZFP80N9kbRRX3TprBx2FpDKRi6YJ6cuFdtxklPP99yRoaVbYAZYFbIgEUCMxhLKAH2sEqenZ7ST89IPjmOErfJOVnvTnDiRZobErc4plu3wES4vN5P2l8w0SdvcUs9j95fWl2Nln2QZUZq8PvL+Q/jspz6IL32VPYlpCr90xs75svTeKtfRv4pG6rOam4JLVED0aYq6zV3Q1EIBrkkkq66EEuOQnLycxBvH/Rjqy3L6q4DMhkHhk3T/ZbbI2rRxWSkXlfZ+/+U30UtOsETOnpLChn9ZApxY2+4xWprPa3EtQxOeIa4vrE7acLrAmd4gytna24r/9G/fi9t3HaHwnFZfTKnli6WUWr4hfDPyNz1VYot2xuPzhG+jwEc3PTtxy6+WMw8vGlZ+zWmz46fCyKXLuOtAQdtdM0R2qd9l7l54wGXy+NPnRpT6jjjLY4XZSbUmbp5kxSjKCMmaIfIBbcOrUmz3E8Q3nXQnWeD9j+/HFz/zDIunLjz/NwTd1Dxj/iyLsawKXNG4bzxHUHU9YVJLffa19fP/8niNSJ7M7lkX/KFpQe1NSqgtNKrSExb0KY+pKU5/v8GJyXgGh9gAKZH5mV6/ToJ8++9+gkWmtxvs+mQJXhrTQmMlvVGjS+z3ybgktwvCS7PV77PnJoT85PJFZY4PHtmOP/mjD6C79U786V+wpjhf1PS8wnelUqhnrLrbN5W91XraMxrWlznsP1CJo4Huy9zZtFy+vmS+/kCUp7GIqraE1lk2by+X38WU1IOtfSb++fs9bHAYGGPf8O9fPIvXTw0r6ksMi6uLW9tzilVVhMS0x7RnqGWhtACq1ATtyTAeYEn7K790iHN7Efzf71bJEqW4mafgww7YCcd3lsc7oFetM9rGeqBaC8yObsECXE3lJ/bo14iv4xMsZdY1rFoAAALOSURBVJ+HA3w/WwmNlSTux2RqS2sCgSSSsSHGcQeScQ8evM/EfXcTsRNpnDx3nfl+BlOz62xsLiutldyuc4b0irZkRJfc79jWjv27ezSvr65EcOykhZ8eI6dPVbWwWWV9UpA1wfX8XkN6l9WrtZh3L49DXXi1fhWfSG9MfKPm5GYk2HWcX+5qVoL+dJMS3Isq6w9HoaEQWVMcC/eyxdatS2wjYRO7dxjYPmBwltlgF9hgGuNcQMC+A6GCZAbaiZ6atjB2g+YZsRgyljYzs+T00qyRvl7V9axQ1TXL6+b5jQVRjZg3jPryWDnmVCo/2XhkRl6BQPtuH8xTPDLWpATnAYrGg4/uZwkcRZge1J4TNOFSjOHRh6VCgTZdZS7PEvm8Ydz0yJxrTW+5zGaJdHDYw5NVHYVSalMd39jC3eJyC21ZdabXcHvUSuA0PeSudGHmKrAJ5iKBjie5y3lszlFCbYG94XpsDpselXU/O4jaM4SOgpznDmqP0+pSXPYcZRGmPmAJu40l6C1zB3a7yoL72cDqpkfmYFmbBLdcjU7XumDUOFxtJgglQs/7soXJl9y6x2YlcLD/B87jc83h4MYFozk8bgoR0xHQWX7jelrUcEqQOt+w3HMTVl0pbneurexszuuNQg5W85xf/cL1j1aGdcGHsoXZF93y3qQAeWk4GObX+fM9Tby4dj2jGSCbwLKmGONmwe39DUU2iFZjcs5BaNTa1nC17JqaN7WnQ3+R4Pb1jvPfr6cL08ObZb2lAmq/MTt83DDNP+RRO5tCwgDcLBGbPAJG7akzA/XHZWsCuxYp3eplWTd7Qs0/cJPgbmGtzVeSY0b44Y9TG9PfvMUBv1AB9WOC3o77PV7zKQLpEX7dzncHzwy5L9EQuDmFYtOT4o2K01V0We7RucS61UMOLotbjcPllacnLfLrGEPihFW2vp8pz76GnyF47fWPAAAA//93utxCAAAABklEQVQDAFPmzZhCNdVFAAAAAElFTkSuQmCC'
const Mark = () => jsx('img', { src: ICON, alt: '', width: 32, height: 32, style: { borderRadius: 8, display: 'block' } })

function Toggle({ label, checked, disabled, onChange, hint }) {
  return jsxs('label', { className: 'gr-toggle', 'data-disabled': disabled || undefined, title: hint, children: [
    jsx('input', { type: 'checkbox', role: 'switch', checked: !!checked, disabled, onChange: (e) => onChange(e.target.checked) }),
    jsx('span', { className: 'gr-switch', 'aria-hidden': true }),
    jsx('span', { children: label })
  ] })
}

function Header({ summary, act }) {
  const s = summary || {}
  const p = s.predictions || { asked: 0, close: 0 }
  return jsxs('header', { className: 'gr-top', children: [
    jsxs('div', { className: 'gr-brand', children: [
      jsx('span', { className: 'gr-mark', children: jsx(Mark, {}) }),
      jsxs('div', { children: [jsx('h1', { children: 'Data' }), jsx('p', { children: `Grimoire ${s.version || ''} · every number has a receipt` })] })
    ] }),
    jsxs('div', { className: 'gr-toggles', children: [
      jsx(Toggle, { label: 'Learning mode', checked: s.learn, hint: 'A short SQL lesson and a better question after data answers',
        onChange: (v) => act.mutate({ path: '/settings', body: { learn: v } }) }),
      jsx(Toggle, { label: s.predict && p.asked ? `Predictions · ${p.close} of ${p.asked} close` : 'Predictions', checked: s.predict, disabled: !s.learn,
        hint: s.learn ? 'Guess the main number before you see it' : 'Turn on learning mode first',
        onChange: (v) => act.mutate({ path: '/settings', body: { predict: v } }) })
    ] })
  ] })
}

function Pending({ pending, act }) {
  if (!pending?.length) return null
  return jsxs('section', { className: 'gr-pending', role: 'status', children: [
    jsxs('div', { className: 'gr-pending-text', children: [
      jsx('b', { children: `${pending.length} merge${pending.length > 1 ? 's' : ''} waiting for you` }),
      jsx('ul', { children: pending.map((m, i) => jsxs('li', { children: [jsx('code', { children: `${m.dataset}.${m.column}` }), ` '${m.from}' → '${m.to}'`] }, i)) })
    ] }),
    jsxs('div', { className: 'gr-actions', children: [
      jsx('button', { className: 'gr-cta', onClick: () => act.mutate({ path: '/merges/approve' }), children: 'Apply' }),
      jsx('button', { className: 'gr-btn', onClick: () => act.mutate({ path: '/merges/reject' }), children: 'Drop' })
    ] })
  ] })
}

function LeanTip({ tip, act }) {
  if (!tip) return null
  return jsxs('section', { className: 'gr-lean', 'aria-label': 'Use fewer tokens', children: [
    jsxs('div', { className: 'gr-lean-text', children: [
      jsx('b', { children: 'Use about a fifth of the tokens with a Data bot' }),
      jsx('p', { children: `Your data chats send ${fmt(tip.tools)} tools and about ${fmt(tip.tokens)} tokens with every model call. A bot with only Grimoire's tools sends about a fifth of that, and answers faster.` }),
      jsxs('ol', { children: [
        jsxs('li', { children: ['Open ', jsx('b', { children: 'Bots' }), ', then ', jsx('b', { children: 'New Agent' }), '. Name it Data.'] }),
        jsxs('li', { children: ['Open ', jsx('b', { children: 'Advanced' }), ' and clone from the profile that has Grimoire.'] }),
        jsxs('li', { children: ['Under toolsets, keep only ', jsx('b', { children: 'Grimoire' }), ' and ', jsx('b', { children: 'Clarifying Questions' }), '.'] }),
        jsx('li', { children: "Ask data questions in the Data bot's chat. Your main agent keeps all its tools." })
      ] })
    ] }),
    jsx('button', { className: 'gr-btn gr-small', onClick: () => act.mutate({ path: '/settings', body: { hide_lean_tip: true } }), children: 'Hide' })
  ] })
}

// Most serious first: a reader should see negative amounts before 9.7% empty cells.
const RANK = ['duplicate rows', 'negative values', 'dates in the future', 'spelling variants of one value', 'same value in every row']
export function issueRank(i) {
  const k = RANK.indexOf(i.issue)
  if (k >= 0) return k
  if (i.issue === 'empty values') return 100 - Math.min(99, i.percent || 0) / 100
  return RANK.length  // placeholders and numbers stored as text
}

function IssueChips({ issues }) {
  const sorted = [...issues].sort((a, b) => issueRank(a) - issueRank(b))
  const rest = sorted.slice(4)
  return jsxs('div', { className: 'gr-chips', children: [
    ...sorted.slice(0, 4).map((i, n) => jsx('span', { className: 'gr-chip gr-issue', children: issueText(i) }, n)),
    rest.length ? jsx('span', { className: 'gr-chip', title: rest.map(issueText).join('\n'), children: `+${rest.length} more` }, 'more') : null
  ] })
}

function issueText(i) {
  if (i.issue === 'duplicate rows') return `${fmt(i.rows)} duplicate rows`
  if (i.issue === 'empty values') return `${i.column}: ${fmt(i.percent)}% empty`
  if (i.rows) return `${i.column}: ${i.issue} (${fmt(i.rows)} rows)`
  if (i.issue === 'spelling variants of one value') return `${i.column}: ${i.variants.map((v) => `'${v.value}'`).join(' / ')}`
  return `${i.column}: ${i.issue}`
}

function Files({ datasets, act, filter, setFilter }) {
  const [armed, setArmed] = useState(null)
  if (!datasets?.length) return jsx('p', { className: 'gr-empty', children: 'No data files yet. Ask Hermes a question about a CSV, JSON, Parquet or SQLite file.' })
  return jsx('div', { className: 'gr-files', children: datasets.map((d) => jsxs('article', { className: 'gr-file', 'aria-current': filter === d.name || undefined, children: [
    jsxs('div', { className: 'gr-file-top', children: [
      jsx('button', { className: 'gr-link', onClick: () => setFilter(filter === d.name ? null : d.name), title: 'Show only this file\'s queries', children: d.name }),
      jsx('span', { className: 'gr-chip', children: d.kind }),
      d.health ? jsx('span', { className: 'gr-chip gr-health', 'data-level': d.health.score >= 90 ? 'good' : d.health.score >= 70 ? 'fair' : 'poor',
        title: d.health.off.length ? `Health ${d.health.score}/100: ${d.health.off.join(', ')}` : 'No data problems found', children: `Health ${d.health.score}` }) : null,
      d.missing ? jsx('span', { className: 'gr-chip gr-warn', children: 'file missing' }) : null,
      jsx('button', { className: 'gr-btn gr-small gr-push', 'data-armed': armed === d.name || undefined,
        onClick: () => { if (armed === d.name) { setArmed(null); act.mutate({ path: `/datasets/${d.name}/forget` }) } else setArmed(d.name) },
        onBlur: () => setArmed(null),
        children: armed === d.name ? 'Click again to delete' : 'Forget' })
    ] }),
    jsx('div', { className: 'gr-path', title: d.path, children: d.path }),
    d.issues?.length ? jsx(IssueChips, { issues: d.issues }) : null,
    d.merges?.length ? jsx('div', { className: 'gr-meta', children: 'Merges: ' + d.merges.map((m) => `${m.column} '${m.from}' → '${m.to}'`).join(' · ') }) : null,
    d.notes?.length ? jsx('div', { className: 'gr-meta', children: 'Notes: ' + d.notes.map((n) => `${n.column}: ${n.note}`).join(' · ') }) : null
  ] }, d.name)) })
}

const TIME = /^\d{4}(-\d{2}(-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?)?)?$/
export const isTime = (values) => {
  const vals = values.filter((v) => v !== null && v !== undefined).map(String)
  return vals.length >= 3 && vals.every((v) => TIME.test(v))
}

export function compact(v) {
  for (const [size, unit] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) if (Math.abs(v) >= size) return `${Number((v / size).toPrecision(3))}${unit}`
  return `${Number(v.toPrecision(3))}`
}

/** Axis labels to draw: evenly spaced so they never touch, always the last one (same rule as report.ticks). */
export function ticks(n, width, labelPx) {
  if (n <= 1) return [...Array(n).keys()]
  const step = width / (n - 1)
  const every = Math.max(1, Math.ceil(Math.floor(labelPx * 1.6) / Math.max(1, Math.floor(step))))
  const keep = []
  for (let i = 0; i < n - 1; i += every) if ((n - 1 - i) * step >= labelPx * 1.6) keep.push(i)
  return [...keep, n - 1]
}

function Line({ q, li, vi }) {
  const rows = q.rows.filter((r) => isNum(r[vi]) && r[li] !== null).sort((a, b) => String(a[li]).localeCompare(String(b[li]))).slice(0, 120)
  const vals = rows.map((r) => r[vi])
  const lo = Math.min(0, ...vals), hi = Math.max(...vals) || 1
  const marks = [lo, (lo + hi) / 2, hi]
  const W = 560, H = 190, B = 22, L = 14 + 7 * Math.max(...marks.map((v) => compact(v).length))
  const x = (i) => L + (W - L - 10) * (i / Math.max(1, rows.length - 1))
  const y = (v) => 8 + (H - B - 8) * (1 - (v - lo) / (hi - lo || 1))
  return jsxs('svg', { className: 'gr-line', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${q.columns[vi]} over ${q.columns[li]}`, children: [
    ...marks.map((v, i) => jsxs('g', { children: [
      jsx('line', { x1: L, x2: W - 10, y1: y(v), y2: y(v), className: 'gr-grid' }),
      jsx('text', { x: L - 6, y: y(v) + 4, textAnchor: 'end', className: 'gr-tick', children: compact(v) })
    ] }, 'g' + i)),
    jsx('polyline', { points: vals.map((v, i) => `${x(i)},${y(v)}`).join(' '), className: 'gr-path-line' }, 'p'),
    ...rows.map((r, i) => jsx('circle', { cx: x(i), cy: y(r[vi]), r: 2.5, className: 'gr-dot', children: jsx('title', { children: `${r[li]}: ${fmt(r[vi])}` }) }, 'd' + i)),
    ...ticks(rows.length, W - L - 10, 7 * Math.max(...rows.map((r) => String(r[li]).slice(0, 10).length))).map((i) =>
      jsx('text', { x: x(i), y: H - 5, textAnchor: i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle', className: 'gr-tick', children: String(rows[i][li]).slice(0, 10) }, 't' + i))
  ] })
}

// Heatmap, histogram and scatter: the plugin's Python picks the chart and orders the data; drawn here.
function Heatmap({ c }) {
  const vals = c.cells.map((t) => t[2]), lo = Math.min(...vals), hi = Math.max(...vals)
  const W = 560, CH = 20, TOP = 20, L = 12 + 7 * Math.max(...c.ys.map((v) => v.slice(0, 14).length))
  const cw = (W - L - 4) / c.xs.length, H = TOP + CH * c.ys.length
  const every = Math.max(1, Math.ceil((7 * Math.max(...c.xs.map((v) => v.slice(0, 8).length))) / Math.max(1, cw - 4)))
  return jsxs('svg', { className: 'gr-line', viewBox: `0 0 ${W} ${H + 20}`, role: 'img', 'aria-label': `${c.value} by ${c.x} and ${c.y}`, children: [
    ...c.xs.map((v, i) => (i % every === 0 ? jsx('text', { x: L + cw * i + cw / 2, y: 13, textAnchor: 'middle', className: 'gr-tick', children: v.slice(0, 8) }, 'x' + i) : null)),
    ...c.ys.map((v, j) => jsx('text', { x: L - 6, y: TOP + CH * j + 14, textAnchor: 'end', className: 'gr-tick', children: v.slice(0, 14) }, 'y' + j)),
    ...c.cells.map(([i, j, v], n) => jsx('rect', { x: L + cw * i + 1, y: TOP + CH * j + 1, width: Math.max(1, cw - 2), height: CH - 2, rx: 2, className: 'gr-cell',
      fillOpacity: 0.12 + 0.88 * ((v - lo) / (hi - lo || 1)), children: jsx('title', { children: `${c.xs[i]}, ${c.ys[j]}: ${fmt(v)}` }) }, 'c' + n)),
    jsx('text', { x: L, y: H + 15, className: 'gr-tick', children: `Stronger color = more ${c.value}: from ${fmt(lo)} to ${fmt(hi)}.` }, 'legend')
  ] })
}

function Histogram({ c }) {
  const top = Math.max(...c.counts) || 1, marks = [0, top / 2, top]
  const W = 560, H = 190, B = 22, L = 14 + 7 * Math.max(...marks.map((v) => compact(v).length))
  const bw = (W - L - 10) / c.counts.length, y = (v) => 8 + (H - B - 8) * (1 - v / top)
  const shown = ticks(c.starts.length, W - L - 10, 7 * Math.max(...c.starts.map((v) => compact(v).length))).filter((i) => i < c.starts.length - 1)
  return jsxs('svg', { className: 'gr-line', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${c.y} per bucket of ${c.x}`, children: [
    ...marks.map((v, i) => jsxs('g', { children: [
      jsx('line', { x1: L, x2: W - 10, y1: y(v), y2: y(v), className: 'gr-grid' }),
      jsx('text', { x: L - 6, y: y(v) + 4, textAnchor: 'end', className: 'gr-tick', children: compact(v) })
    ] }, 'g' + i)),
    ...c.counts.map((n, i) => jsx('rect', { x: L + bw * i + 1, y: y(n), width: Math.max(1, bw - 2), height: Math.max(0, y(0) - y(n)), rx: 2, className: 'gr-cell',
      children: jsx('title', { children: `${fmt(c.starts[i])} to ${fmt(c.starts[i] + c.step)}: ${fmt(n)}` }) }, 'b' + i)),
    ...shown.map((i) => jsx('text', { x: L + bw * i, y: H - 5, textAnchor: i === 0 ? 'start' : 'middle', className: 'gr-tick', children: compact(c.starts[i]) }, 't' + i))
  ] })
}

function Scatter({ c }) {
  const xs = c.points.map((p) => p[0]), ys = c.points.map((p) => p[1])
  const xlo = Math.min(...xs), xhi = Math.max(...xs), ylo = Math.min(0, ...ys), yhi = Math.max(...ys)
  const W = 560, H = 230, B = 40, TOP = 22, L = 14 + 7 * Math.max(...[ylo, (ylo + yhi) / 2, yhi].map((v) => compact(v).length))
  const x = (v) => L + 6 + (W - L - 20) * ((v - xlo) / (xhi - xlo || 1)), y = (v) => TOP + (H - B - TOP) * (1 - (v - ylo) / (yhi - ylo || 1))
  return jsxs('svg', { className: 'gr-line', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `${c.y} against ${c.x}`, children: [
    ...[ylo, (ylo + yhi) / 2, yhi].map((v, i) => jsxs('g', { children: [
      jsx('line', { x1: L, x2: W - 10, y1: y(v), y2: y(v), className: 'gr-grid' }),
      jsx('text', { x: L - 6, y: y(v) + 4, textAnchor: 'end', className: 'gr-tick', children: compact(v) })
    ] }, 'g' + i)),
    ...[xlo, (xlo + xhi) / 2, xhi].map((v, i) => jsx('text', { x: x(v), y: H - 22, textAnchor: 'middle', className: 'gr-tick', children: compact(v) }, 'x' + i)),
    jsx('text', { x: L, y: 12, className: 'gr-tick', children: `${c.y} ↑` }, 'yn'),
    jsx('text', { x: (L + W) / 2, y: H - 4, textAnchor: 'middle', className: 'gr-tick', children: `${c.x} →` }, 'xn'),
    ...c.points.map(([a, b], i) => jsx('circle', { cx: x(a), cy: y(b), r: 4, className: 'gr-pt', children: jsx('title', { children: `${c.x} ${fmt(a)}, ${c.y} ${fmt(b)}` }) }, 'p' + i))
  ] })
}

const CHARTS = { heatmap: Heatmap, histogram: Histogram, scatter: Scatter }

function Bars({ q }) {
  const pick = chartColumns(q.columns, q.rows)
  if (!pick) return null
  const [li, vi] = pick
  if (isTime(q.rows.map((r) => r[li]))) return jsx(Line, { q, li, vi })
  const rows = q.rows.filter((r) => isNum(r[vi])).slice(0, 25)
  const top = Math.max(...rows.map((r) => Math.abs(r[vi]))) || 1
  return jsx('div', { className: 'gr-bars', role: 'img', 'aria-label': `${q.columns[vi]} by ${q.columns[li]}`, children: rows.map((r, i) => jsxs('div', { className: 'gr-bar-row', children: [
    jsx('span', { className: 'gr-bar-label', title: String(r[li]), children: fmt(r[li]) }),
    jsx('span', { className: 'gr-bar-track', children: jsx('span', { className: 'gr-bar', style: { width: `${(Math.abs(r[vi]) / top) * 100}%` } }) }),
    jsx('span', { className: 'gr-bar-value', title: fmt(r[vi]), children: Math.abs(r[vi]) >= 10000 ? compact(r[vi]) : fmt(r[vi]) })
  ] }, i)) })
}

function Result({ q }) {
  if (q.rows.length === 1 && q.columns.length <= 4 && q.rows[0].every((v) => isNum(v) || v === null))
    return jsx('div', { className: 'gr-kpis', children: q.columns.map((c, i) => jsxs('div', { className: 'gr-kpi', children: [jsx('b', { children: fmt(q.rows[0][i]) }), jsx('span', { children: c })] }, c)) })
  const numeric = q.columns.map((_, i) => q.rows.length > 0 && q.rows.every((r) => isNum(r[i]) || r[i] === null))
  return jsxs('div', { children: [
    CHARTS[q.chart?.kind] ? jsx(CHARTS[q.chart.kind], { c: q.chart }) : jsx(Bars, { q }),
    jsx('div', { className: 'gr-table-wrap', children: jsxs('table', { className: 'gr-table', children: [
      jsx('thead', { children: jsx('tr', { children: q.columns.map((c, i) => jsx('th', { className: numeric[i] ? 'gr-num' : '', children: c }, i)) }) }),
      jsx('tbody', { children: q.rows.map((r, n) => jsx('tr', { children: r.map((v, i) => jsx('td', { className: numeric[i] ? 'gr-num' : '', children: fmt(v) }, i)) }, n)) })
    ] }) }),
    q.total_rows > q.rows.length || q.truncated ? jsx('p', { className: 'gr-muted', children: `Showing ${q.rows.length} of ${q.truncated ? 'more than ' : ''}${fmt(q.total_rows)} rows.` }) : null
  ] })
}

function Explain({ id }) {
  const data = useData(`/queries/${id}/explain`)
  if (data.isLoading) return jsx('p', { className: 'gr-muted', children: 'Loading…' })
  if (data.error) return jsx('p', { className: 'gr-error', children: errorText(data.error) })
  return jsx('pre', { className: 'gr-explain', children: data.data.text })
}

function Detail({ q }) {
  const [explain, setExplain] = useState(false)
  const copy = () => navigator.clipboard.writeText(q.sql).then(
    () => host.notify({ kind: 'success', message: `Copied the SQL of ${q.id}` }),
    () => host.notify({ kind: 'error', message: 'Could not copy. Select the SQL and copy it.' }))
  return jsxs('div', { className: 'gr-detail', children: [
    jsxs('div', { className: 'gr-detail-head', children: [
      jsx('span', { className: 'gr-qid', children: q.id }),
      jsx('h2', { children: q.purpose || 'Query' })
    ] }),
    q.question ? jsx('p', { className: 'gr-question', children: `“${q.question}”` }) : null,
    jsx(Result, { q }),
    jsxs('div', { className: 'gr-sql-head', children: [
      jsx('span', { children: 'SQL behind these numbers' }),
      jsx('button', { className: 'gr-btn gr-small', onClick: copy, children: 'Copy' }),
      jsx('button', { className: 'gr-btn gr-small', 'aria-expanded': explain, onClick: () => setExplain(!explain), children: explain ? 'Hide explanation' : 'Explain' })
    ] }),
    jsx('pre', { className: 'gr-sql', children: q.sql }),
    explain ? jsx(Explain, { id: q.id }) : null,
    jsx('p', { className: 'gr-muted', children: `${ago(q.created_at)} · ${q.datasets.join(', ') || 'unknown file'} · type /grimoire rerun ${q.id} in chat to check it still holds` })
  ] })
}

function Queries({ filter }) {
  const data = useData(filter ? `/queries?dataset=${filter}` : '/queries')
  const [selected, setSelected] = useState(null)
  if (data.isLoading) return jsx('p', { className: 'gr-muted gr-pad', children: 'Loading…' })
  if (data.error) return jsx('p', { className: 'gr-error gr-pad', children: errorText(data.error) })
  const list = data.data.queries || []
  if (!list.length) return jsx('p', { className: 'gr-empty', children: 'No saved queries yet. Every answer about your data saves one here, with its SQL.' })
  const current = list.find((q) => q.id === selected) || list[0]
  return jsxs('div', { className: 'gr-split', children: [
    jsx('nav', { className: 'gr-list', 'aria-label': 'Saved queries', children: list.map((q) => jsxs('button', { className: 'gr-item', 'aria-current': q.id === current.id || undefined, onClick: () => setSelected(q.id), children: [
      jsxs('span', { className: 'gr-item-top', children: [jsx('span', { className: 'gr-qid', children: q.id }), jsx('b', { children: q.purpose || q.question || q.sql })] }),
      jsx('span', { className: 'gr-item-sub', children: `${ago(q.created_at)} · ${q.datasets.join(', ')}` })
    ] }, q.id)) }),
    jsx(Detail, { q: current }, current.id)
  ] })
}

function GrimoirePage() {
  const summary = useData('/summary')
  const act = useAction()
  const [filter, setFilter] = useState(null)
  return jsxs('div', { className: 'gr-page', children: [
    jsx('style', { children: CSS }),
    jsx(Header, { summary: summary.data, act }),
    summary.error ? jsx('p', { className: 'gr-error gr-pad', children: `Grimoire is not reachable: ${errorText(summary.error)}. Check that the plugin is enabled.` }) : null,
    jsxs('main', { className: 'gr-body', children: [
      jsx(Pending, { pending: summary.data?.pending, act }),
      jsx(LeanTip, { tip: summary.data?.lean_tip, act }),
      jsxs('section', { children: [jsx('h3', { className: 'gr-h', children: 'Files' }), jsx(Files, { datasets: summary.data?.datasets, act, filter, setFilter })] }),
      summary.data?.metrics?.length ? jsxs('section', { children: [
        jsx('h3', { className: 'gr-h', children: 'Saved metrics' }),
        jsx('div', { className: 'gr-chips', children: summary.data.metrics.map((m) => jsxs('span', { className: 'gr-chip gr-metric', title: 'Remove with /grimoire undefine ' + m.name, children: [jsx('b', { children: `${m.name}()` }), ` = ${m.expression}`] }, m.name)) })
      ] }) : null,
      jsxs('section', { className: 'gr-grow', children: [
        jsxs('h3', { className: 'gr-h', children: ['Saved queries', filter ? jsx('button', { className: 'gr-chip gr-filter', onClick: () => setFilter(null), children: `${filter} ×` }) : null] }),
        jsx(Queries, { filter }, filter || 'all')
      ] })
    ] })
  ] })
}

const CSS = `
.gr-page{height:100%;min-height:0;display:flex;flex-direction:column;color:var(--foreground);font-size:13px;overflow:hidden;container-type:inline-size}
.gr-page *{box-sizing:border-box}.gr-page :focus-visible{outline:2px solid var(--ui-accent);outline-offset:-2px}
.gr-muted{color:var(--ui-text-tertiary);font-size:12px;margin:8px 0 0}.gr-error{color:var(--ui-red,var(--ui-error,var(--foreground)))}.gr-pad{padding:0 20px}
.gr-empty{color:var(--ui-text-tertiary);margin:6px 0 0}
.gr-top{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:16px 20px 12px;border-bottom:1px solid var(--ui-stroke-secondary)}
.gr-brand{display:flex;align-items:center;gap:10px;min-width:0}.gr-brand h1{margin:0;font-size:16px;font-weight:600}.gr-brand p{margin:1px 0 0;font-size:12px;color:var(--ui-text-tertiary)}
.gr-mark{width:32px;height:32px;flex:none;border-radius:8px;overflow:hidden}
.gr-toggles{margin-left:auto;display:flex;gap:16px;flex-wrap:wrap}
.gr-toggle{display:inline-flex;align-items:center;gap:8px;cursor:pointer;color:var(--ui-text-secondary)}.gr-toggle[data-disabled]{opacity:.5;cursor:default}
.gr-toggle input{position:absolute;opacity:0;width:1px;height:1px}
.gr-switch{width:28px;height:16px;border-radius:8px;background:var(--ui-stroke-secondary);position:relative;transition:background .15s;flex:none}
.gr-switch::after{content:'';position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--background);transition:transform .15s}
.gr-toggle input:checked+.gr-switch{background:var(--ui-accent)}.gr-toggle input:checked+.gr-switch::after{transform:translateX(12px)}
.gr-toggle input:focus-visible+.gr-switch{outline:2px solid var(--ui-accent);outline-offset:2px}
.gr-body{flex:1;min-height:0;overflow:auto;padding:16px 20px 24px;display:flex;flex-direction:column;gap:18px}
.gr-h{margin:0 0 8px;font-size:12px;font-weight:500;color:var(--ui-text-secondary);display:flex;align-items:center;gap:8px}
.gr-pending{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:12px 14px;border-radius:8px;border:1px solid color-mix(in srgb,var(--ui-accent) 40%,transparent);background:color-mix(in srgb,var(--ui-accent) 8%,transparent)}
.gr-lean{display:flex;gap:16px;align-items:flex-start;padding:12px 14px;border-radius:8px;border:1px solid var(--ui-stroke-secondary)}
.gr-lean-text{flex:1;min-width:0}.gr-lean p{margin:4px 0 0;color:var(--ui-text-secondary)}.gr-lean ol{margin:6px 0 0;padding-left:20px;color:var(--ui-text-secondary);display:flex;flex-direction:column;gap:2px}
.gr-lean ol b{color:var(--foreground);font-weight:500}
.gr-pending-text{flex:1;min-width:0}.gr-pending ul{margin:4px 0 0;padding-left:18px;color:var(--ui-text-secondary)}.gr-actions{display:flex;gap:8px}
.gr-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--ui-stroke-secondary);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer;color:var(--foreground);background:transparent}
.gr-btn:hover{background:var(--chrome-action-hover)}.gr-small{padding:3px 9px;font-size:12px}.gr-btn[data-armed]{color:var(--ui-red,var(--foreground));border-color:currentColor}
.gr-cta{border:0;border-radius:7px;padding:7px 14px;font:inherit;font-weight:600;cursor:pointer;color:var(--background);background:var(--ui-accent)}
.gr-files{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.gr-file{min-width:0;padding:10px 12px;border:1px solid var(--ui-stroke-secondary);border-radius:8px;display:flex;flex-direction:column;gap:5px}
.gr-file[aria-current]{border-color:var(--ui-accent)}
.gr-file-top{display:flex;align-items:center;gap:6px;min-width:0}.gr-push{margin-left:auto}
.gr-link{border:0;padding:0;background:none;font:inherit;font-weight:600;color:var(--foreground);cursor:pointer;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gr-link:hover{color:var(--ui-accent)}
.gr-path{font-family:var(--font-mono,ui-monospace,monospace);font-size:11px;color:var(--ui-text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;text-align:left}
.gr-chips{display:flex;flex-wrap:wrap;gap:4px}
.gr-chip{display:inline-flex;align-items:center;font-size:11px;padding:1px 7px;border-radius:5px;border:0;font-family:inherit;color:var(--ui-text-secondary);background:var(--chrome-action-hover);white-space:nowrap}
.gr-issue{color:var(--ui-yellow,var(--ui-text-secondary));background:color-mix(in srgb,var(--ui-yellow,var(--ui-text-tertiary)) 14%,transparent);max-width:100%;overflow:hidden;text-overflow:ellipsis}
.gr-health[data-level=good]{color:var(--ui-green,var(--ui-text-secondary))}.gr-health[data-level=fair]{color:var(--ui-yellow,var(--ui-text-secondary))}.gr-health[data-level=poor]{color:var(--ui-red,var(--foreground))}
.gr-warn{color:var(--ui-red,var(--foreground))}.gr-metric{font-family:var(--font-mono,ui-monospace,monospace);white-space:normal}.gr-metric b{font-weight:600;margin-right:2px;color:var(--foreground)}.gr-filter{cursor:pointer}
.gr-meta{font-size:12px;color:var(--ui-text-tertiary);overflow-wrap:anywhere}
.gr-grow{flex:1;min-height:320px;display:flex;flex-direction:column}
.gr-split{flex:1;min-height:0;display:flex;border:1px solid var(--ui-stroke-secondary);border-radius:8px;overflow:hidden}
.gr-list{width:min(38%,340px);min-width:200px;overflow:auto;border-right:1px solid var(--ui-stroke-secondary)}
.gr-item{display:block;width:100%;text-align:left;padding:9px 12px;border:0;border-bottom:1px solid var(--ui-stroke-secondary);background:transparent;color:inherit;font:inherit;cursor:pointer}
.gr-item:hover{background:var(--chrome-action-hover)}.gr-item[aria-current]{background:color-mix(in srgb,var(--ui-accent) 10%,transparent)}
.gr-item-top{display:flex;gap:8px;align-items:baseline;min-width:0}.gr-item-top b{font-weight:500;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-item-sub{display:block;margin-top:3px;font-size:11px;color:var(--ui-text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gr-qid{flex:none;font:600 11px var(--font-mono,ui-monospace,monospace);color:var(--ui-accent)}
.gr-detail{flex:1;min-width:0;overflow:auto;padding:16px 20px}
.gr-detail-head{display:flex;gap:8px;align-items:baseline}.gr-detail-head h2{margin:0;font-size:16px;font-weight:600;overflow-wrap:anywhere}
.gr-question{margin:4px 0 12px;color:var(--ui-text-secondary)}
.gr-kpis{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}.gr-kpi{display:flex;flex-direction:column;padding:10px 14px;border:1px solid var(--ui-stroke-secondary);border-radius:8px;min-width:130px}
.gr-kpi b{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}.gr-kpi span{font-size:12px;color:var(--ui-text-tertiary)}
.gr-bars{display:grid;grid-template-columns:minmax(60px,max-content) minmax(80px,1fr) max-content;gap:4px 10px;align-items:center;margin:10px 0;max-width:640px}
.gr-bar-row{display:contents}.gr-bar-label{text-align:right;color:var(--ui-text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px}
.gr-bar-track{height:12px}.gr-bar{display:block;height:100%;min-width:2px;border-radius:2px;background:var(--ui-accent)}
.gr-bar-value{font-variant-numeric:tabular-nums;color:var(--ui-text-secondary);font-size:12px}
.gr-cell{fill:var(--ui-accent)}.gr-pt{fill:var(--ui-accent);stroke:var(--background);stroke-width:2}
.gr-line{width:100%;max-width:640px;margin:10px 0;display:block}.gr-path-line{fill:none;stroke:var(--ui-accent);stroke-width:2}
.gr-dot{fill:var(--ui-accent)}.gr-grid{stroke:var(--ui-stroke-secondary)}.gr-tick{fill:var(--ui-text-tertiary);font-size:11px}
.gr-table-wrap{overflow-x:auto;margin-top:8px}.gr-table{border-collapse:collapse;font-size:12px}
.gr-table th,.gr-table td{padding:5px 10px;border-bottom:1px solid var(--ui-stroke-secondary);text-align:left;white-space:nowrap}
.gr-table th{font-weight:500;color:var(--ui-text-secondary)}.gr-num{text-align:right!important;font-variant-numeric:tabular-nums}
.gr-sql-head{display:flex;align-items:center;gap:8px;margin-top:16px;font-size:12px;color:var(--ui-text-secondary)}.gr-sql-head span{margin-right:auto}
.gr-sql,.gr-explain{margin:6px 0 0;padding:10px 12px;border-radius:6px;background:var(--chrome-action-hover);font:12px/1.5 var(--font-mono,ui-monospace,monospace);white-space:pre-wrap;overflow-wrap:anywhere}
@container (max-width:560px){.gr-split{flex-direction:column}.gr-list{width:auto;max-height:200px;border-right:0;border-bottom:1px solid var(--ui-stroke-secondary)}.gr-toggles{margin-left:0}}
`

export default {
  id: ID,
  name: 'Grimoire',
  defaultEnabled: false,
  register(ctx) {
    pluginCtx = ctx
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: '/grimoire' }, render: () => jsx(GrimoirePage, {}) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/grimoire', label: 'Data', codicon: 'database' } },
      { id: 'open', area: PALETTE_AREA, data: { id: 'grimoire.open', label: 'Open Grimoire data', keywords: ['data', 'csv', 'queries', 'grimoire'], run: () => host.navigate('/grimoire') } }
    ])
    ctx.onEvent('gateway.ready', () => queryClient.removeQueries({ queryKey: [ID] }))
    ctx.onDispose(() => {
      queryClient.removeQueries({ queryKey: [ID] })
      pluginCtx = null
    })
  }
}
