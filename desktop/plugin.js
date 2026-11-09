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

// The Grimoire icon: Hermes Trismegistus (engraving by Jean-Louis Durant, 1675, public domain), 64 px.
const ICON = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAQAElEQVR4nKx7B3hc5bXtml40ozLq1UWyJbl3GzdsMNgUYwO5tBsCCSGXl5DcvCQ3DZLHfflIT24SkrwXSIDwIIUApmMC2NhgyzauclOxZKv3PqPpM2/tPZIsueGP7x5/45nRzJzz7/3vvfba5Zjx8Ydh4cKFK0Kh0A12u215VnZBud1uSfP7A+ZQMACzxY5wKIDc3Gz09PRicMiPvJx0mMxmWK1WtLd3w+NJQU5ONir27ONzDqwWMxYtWoBjx47jjTe3oXR6EdzuFKSmpqCvrx8Gg0FfW/j7rVu3IxYLnV2MwYKpU/LB9cDn88HnDyMUHEZqSnJ02bIlfYOD3pNDQwMVJpPpjW3btn3An8QvKdwlPjMWFhbe63IlfweIlsRiMdhtdhhMFkQo8IyZ5ThypBJNzR28RBibbroRXq8XLgoSCvqRnu7B8LAf7uRUeNKSUVVdA7fLBZs9iZ/7cNOmm/DVf/8aunoGceftm9Hb24eUlBR0dHbDbDbCQgVGo1EYzXY0NtSjubkFTqcDJSWl/HuQ5x5Gfd1peIdDev2Ecgy47fY70drcgO6eHn7HV5fkzvjR/n27nuLHsQsJabrQHzMzM0vS0tJe9/v9XwoEwx7Z6Wg0hnAkjHA4hqysdCQ5nViwgLt49AQ/C/P1fN3xSDiKvNwcXbzJSEEsVjQ2NiIpyQmHw4EYz5OZmY5Tp+rQ1z+AzKwsrF61AvF4TBdtp4IcdovuvtFk4jnt3F0XrSobxSXFWLp0Ma2kD/l5efBRCVwnrSGoFiFHbW09pk4tGrEko8dsstyUlpZyHT/aQaX1fqwCKPyGcDj8TiQSLk5yJtFkcylwJvJ4wVwuYtKkyRQwGxmZGWrONDXU19erkHfccTuy+Z2hoUF1Bwd3jBZE83bSemy0xTgX7EFhYT7mz5+P/v5+pKWmoburEzablX8voOIiSPd4aCUh+ClgekYGv5OMhqYmdHV1ISc7FwH/MDzpCSXaqKjp06epwgcHB0H96vcHBwZhMAIFBUW0KEO+2WS+t7Ao/3Bra/upiyogNzd3QzBkeJVO44zxP5vdQbsyI5OLEPPKzc/nhTNgptCZmVm0hghycvOwu2IfgqEIqmnmq1dfKZqnMIVIpvkvXLQIM2fORGFREVIobDYF4HZj2rRpyMjIRGtrG5LdydxtMxftVR9PdrtgNJp5bRMVbKGAJZgzew4mTy7CPffey+9a0NHegUAgTCUn8TcmWpcTySmpXEdUXXFg0MvfleHQkWPEoQ5ev9DmHw7elptbfKC9van2PAVkZGSU0ozejcZijiSnFU6HHV7upN1u54W8FMZNH07ibnVh54738d5779Evm1BcPBVnTp8iIA1xBwaw/8BhLihK7RvUZf7fs3/Br3/9azXTGHdXvr+nogI//snPsG7dVZgzZwaKigqJHUmYPGUSz3WaC27FwMCAgufGjTfQuhogWLZw4QJVnJmrPnz4IC3ER2tJI16YaKUZuuZYVMBxELRgxaLu7h66pR9tra3EmR6TP+DfXF5e+lJbW1u34sYo4KWnp++hzy82Wxw8IRTExLz7B3xIS0miL1sIfDPQ2taF2TNL1dTdLjeS+Pjd736HmpoRpXIHR0Hpct7bHS7EifKbCYpTpk7BiRM1KKYPF00qwr59+3HV2jVYvmI5/vj4H7GE/r98xUps2/YenLTOrW+/jd5+Lxw2MwWOMHKkoqGxmVHGhLq6eq59AF3dA4hGAhOu77Cb9/f09Czlu5haAH35XgLEF0VIMSUbTyivxcdTabYwxBEKh+lLZixZvISmXoVhv1+/M5umuYMW0dXVPXIBOeU4wP2Y95FonAsM4/jxE/jww90oL59JrMlSM968aRPdZwbuvPPTuP/++yhkFCW0gBq6WiAQwLpr1qGmqoam70ZzU7Nijslk1M0bGhpSnMqlDEGCeF5errqxgS4d8PvyPB5PE8PoIbMsKRSKfls0Y7U5abpWfokmwedgMILs3AL4vP0w0q/d9E3GWSxcvIzCm9WcW1ta4fUFEzsrJzNauKPj5L3E+yRGiUU85yKnCWVE/rKVK5FfkAP7jFIKGITVN4CTP34ad2V6sGDGDBw4flx/Z2FkePIPj2Pt2ivVOmprajBz1mwF3mF/BPPmTcPJagKkzcGNCxC4p6pCc/MK4VfeoJHjW0DHk2ai+wqi53TxBTFFV1Iy47abzy6SHBNcTjumTi5XQV3EgHg8CneSTaIFTtVWYzFBrrOjdcysVbhxJn6h99NswOcyk7E+NQk2KkEOU1Y2PHfeiTj92khQNBPVhz98HwWdTZhxx12wdXVgeVGB+mxBXg6t5UPs378fjz/+B0F5WEzc3XgE165bS/zoxfy5M9HQ0EjBySUMMVq2lZYWoVJMKJ1Whrb29mlLl85faSTwbRSSY+RCxHwiNHUxnwECmhCZ9vZ2+uUJgpSLppWhOy/+ZuazoHsbEZasEJdz5FOhv5qUji3T87DJ44ad1xSzlGsn33Ibou0tYGiBZWoJIi1N4FbxMxNs5bOoIRPi3EULwXWW1YhfFKTDQ/7x+fu/SEGbkEYwzMvPQ0dHO7LJLWbRItxut4ZsYaFksQyRMeUmAbpEdnY2f9dyk5Hx8wpZgIssTfzdQYIj4BdjHBTiQl+hUiLKxAYZFcSnRAkSHfK4E6+88uplCX97uhuvleXj2hS7Cqz+SGGMfE5afz1spTMQ6+mmEloRIy+wTi7mjsZhX7AQMe8gzFm5iAf8UNxmsF+X7MSW4hxschrw7HN/xW8e+z/Yu3c/qmpO4TsPfY/gakdZWSlNPczNHOQm+ZW8iSKGBoeUanPzlxlSPdntDE/ZaURQE8NJcnIalWFXpiWastmSMHPGND2BEBW3O1XNqb6uDsuWL8P1N/wLzTp8jo+ffW8hlvygwI2NqXbFFgP0PxjJEB2r18AsRKVwMoL798B5/SaETx6HdcZsDD73JAwkT7Z5i2DKzlG3MBGPjBQicKwS7V99gO4YF0qB1wdDeKStHxG+Gb2+x5OKn//0hwhFYmSrR5ULNDQ0MJgKCHrJFqdwI20dJrvd8ShiYZPZQhfgjoigwwQfn8/LZy+BMMh46yWDS9F4W3WymuZVjrLS6XjhHy/gwIFDIz4ewxi6j7y30Pd+MzmTu24bQeCzD9cNm3W3Q8eOIOVzDyBKH7dQGRAK7UmnwClwrFitz5HmRpjzChBpa9bPwvV1GH7/vTElT7cZUcbHu0M+ROOJ6/vJFt98a6tijlB3WX8xhRZab7WalE0eOnTQZiZrs4bo0xEFCDtSklOQkZ6i3L2kuETZVRqTGRt3IykpiVxgtuYF//Vfv8Zrr78xhv7nHgJWPyrMwGq3dUToRLIi/ywl02Aiu3Tffjd8L/9d/d3odCGweycc629AYMd78O/cBtuSK+C85nqa/jAMpLwmMkuj3YlYb88Igzmby61yOfC/c9Lw3XbvWPpHSs81vjkGwhkZ6SgonELhh5S6Uw6hPIljaMirfp+ckqZWIAKfrKpiaHRgw/p1RNZBJhqnsGv3Xhw/dhQCnJc6BOWvS3XpEkdNX/8RrZPvuR9mhqZIazPitDLxfTOps2X1Wgy/9hJiQ/2wksY612/E8NuvwTZ3ISwMYfFIQpDQqeqEK43PdPl2Q4oT1cwhnu4NX3BNwgq7mX2OKkRkNIvPjO6ij6ll7akG9SFBzn+96w61AOHajz76M0VR9bG4aYTQXDjOlzGx+Qp3Y/yuJ17zorPmwr5kBQK73keEaS6odCMB2JiehcFfPgr7uusQOVNP4BtCuOY43Hfei/5f/hBGJlEWYoWIHG1v03NBVTD2Qv/7YmYKKobjVET4ousbe0+5jQpY8bOP0fft9LfjBJtIOIi3396qOfj4z8/9/tiD7x/OdVOzCbA7+0howH7FKsTofwJ+JgoV7+uBZeY8eH/7M5iYYBnILu1rroF96QqYqJQ4fdb96fvQ/5P/HLOAqPAOQ+LE408vL8Skv53lYAQJX9Z6jRcyFSlGiL93MvHx+ob1/eUea5MdmEuihPFmP84CzCxoyIvAtrcQbTgNc26++riRVhOtrVKmFCcHsZTPpq93KzgKABoZomPkASKnmRnlGASMK+mMKmKOw4bVsobLOM5TgAieS948ixxc8nIH42kan+WQ3Pvjjs/T9yesa+wNYz5B1jq9HAwtigES2iJVRzH08P+EZc582JZfiVhrCyKN9Qju2wXrnIUIn6jU09iXrYCBvEQOK4H4nFNjvLnJ//d6XLicwziGASOPfJqmxepklpdMfj0HH35QQW6QQs69Ci9teQlXXLFswvfH/34qEXq2w3SO4GdfmqeVMrYzvd75LoZ+9RP4n3+WYS0DpinFiNZUwTxnHqw0fyNz/FiHhMhDcF53M6JEfVGGYIMumtcZs/kRCzu3uDfbbsVkAvi58p37/jwMyMvJQF9PJ2lvGstK3UwsZjN+TsZNN65nstGFrs62i/rUNW7zyDrOSj/eEqxCaUURhUVwbv6XBKk7XYfoof2I7K9AhGHQyChkXXU1LDPmgESEBKkCse6OhGuQieqpbDZMPPl5UVH1c3WS8WMxYIJzp6Qka+iTwoPw/5tu2sic/AB5c6IGKC5Rf7oRFzsWk0GOX5hhvAnwsIj/yw5SSNOUqTBREam//bP+LTbQj/DBvYjW12h0sK1ZD61pkZwZaIEG8gSN/zwELC/nWEQs+FNf6JLfmYABkg/kMEk4cfKkmrr4/OzZMzUJmsIFv0zeL1zhYsdMxwhGxEef4hPeW0hxhdezpgUDXcxEHIj7fYicJK8Y7EOk8iAiJ44SHIkBdBNz6UzEWPoWwWNDA2SAtQkFpKXjco4ZNsvHfmcCD5Cafmt7NdZfcyV2797HbK8cLa1dWgi1sVBy8GDlReNqJmlyknFUn6NKMugrMQAT0d5A3/a/sQWB995K0F2eM/jBdqW/sYE+mGfMgiErD8aiKSRHXQRL0tY5CzQSxKkIY2oCjOP8/oTLYIwGTDictJ4Mrqs7cv56E2/Ow4AITOTvtQxH1157FanwFD6KtKp7YP9H5P0fXdSnPKYoEns+btfHvbQtvkIFNpLOWhcsQfjoEVjI8MJHD2P4mScQJg4Ed+2EuWgSQrt30OxT1ZGjbS1MhvLUDaJd7Xq+MGuQmgWNXORCwo++TTNELp8HGKmxGE9cWFCoKfELL7xIn2/Qz6QucKlDtD0qdHz8euIJS3Bu2IhQNSs63BHr4uVIfugHsJIUWagMY34hs8BjMJfNQrS7GzHW+NXfWSkO1Z5EnHUBEyvIpvRMPWVg7+6JOh6njHMVouu6xDEBBKW2Xsosz0pSIvk+qya44caNyvulTn+pIzx+B0Z33pB4YV+0FBEWOyTJCR3YB2vZDJgodIxFSzPzfudn7keUCZFt+Rp+XgFz8XTlBRF2eEyZORh+9QX9W4TFDjljjOuMT9DA2cvGz/6nj0g8fmkFjGKAtKWkSCCNDAv7aZ0//AAAEABJREFUffG4EbO5iBkzZvIztyZBo3H0QhjgixkT1zWcvaAhntC+86prE+kteb4wOlNGljLAwLatiNCcXfd/RSNDqPIALaALjo23wv/Om4j19cK++mpmiDcSLIc1LZbDQkAOUJGjuz1B5vH7wPfeuFldSQq6YtUhdrbOwwCpAc4oL2H9z8pCSJbW46XhuXjRPO5+FB99tI+NzMpLcusWfl/cZ5wl6gJYb4d95VqSGuYVTQ1qvv733sbA738JE3ffSOI18JPvw7flbzBPnY4wyY4QHaMkYQy9IrSRpXeJHDF2iuJ0DzvxJB4ft9vjpB//J5Gzj0IbEGGN04pHf/A93HrLjWy1Oc/yAA9raakpSfoDJy945kwDU+N+Pp9hU+JGlJXP0Nz5444Qf9/C0lmh1TLBClw33671PMntw3U1cNAa/Nv+CYnAvldeQMqD34DzxlslN9XCaJTlsEDFTliIB3Hm8wnkN2g2GOdmxJmc2RkZhAzFWCIbL3B8gjLiaGW3ah7L+OuvXcusNhk9TIevveZqzGZB56c//bnWQEzstT0ixVBhTt0EID/bTbL7V65ejaXLlqrpvMGignyWMJuL1/nLWdou5WM0AbJOnor0bzzMhUdgZLV5+N0Rs166HI61zPhYXjeyuWmZOk1dhEU68vy5rPy0ahZozslT4BMLiDSdofAR/p7ZI/lDsOYkwg1nVOCz/8Yrgzq9aTM6+Pv7Pv85VoSj2lSVvEaKPZPYeGliL8EYpa/39g2wUNCvvh+JGtiBvQJTi6dBah5G+ngq+frFuPT49x94wyN1ujgs00uR9eNfcfepXNbxjUxkXJ+6C8asHArHmv/MOXSPDNLjOYiSA0iqa5A23OH9NHUvrAQ9wQrf1lfhffNldQkBU0mlY1SOc9XasWudCwQmKjX7a9/EbosTDzzwACp272aR1IEn/vRnhvg6Uvo+7W3eeuutMPb1dpHxmWC3mln16VMskIGDNtYDXmbyU8f6m0tSy8vIr3eyJuej0oTwpN3/JSUsYaL7MMmOl4IMf/A+LEyI2HXV9YaYAMWYCpvzixDlzvb99ucYfPZJBI8fQ4T5CMMRHEyOxBqkehQja5RdN9L8HUuZlJktY6Y/WiCVR+YDD8J15dVYsflm7raD7bEe/P1vf6X5r1VuE6YbCbbJs1Hor5SpvSxNFRTka4MxmRHBQ59bRjosbe3Dh47gco4wz9N2810oePI5hOpq4eduqinn5bOstUD/FqULGHjNcOMZDDz7NDq//iV4X3kefiZC3rdeg5EMUQQ15eRrAiQ1gDBdIiJ0mL91sXIsh9QHXRuuP0f4xGv/ieMIMdWWBusXvvAldrfTMYstvNV062G/1Dcs6Ovt1TagKTXF84gQIOnbCw4EWUoaYGIiww7S/JQe3LFjx7QX+HEY8NV/fxBNgRAWWIi7dae4SDesU0rUrIk4Go4MvLiRjU3pA4hlSIU32t+n4S/S1gYHd05ospUuGO3vJxGq4iLTNCUmIGG44gO6S0SV4iSW+MlO5ffjScFgczP6lq+iGxdrmz4nNwcC9jI/UFd3mhseRxO/I9zG5EpOf0T6/V6fXztBreT+0gOMsJ6ex53LJDJXHj2hPUERVn1+VHA+ZEZoLTu43/j613H3Z+5G36Af6WncHQKf78MdGr8dBDuTZIDs1AQqD7G2NwmBIwfVp4f37NbPFPi4e2GWyt033Swsim7zGhsi2Xo5a8l0fvdDOJcsR4hKkwjgXLQMKRtvgZW5iu+jvcog5RxPtPeiZOMmrr9ABy+kGDrIZsgTTzzFFvxUBUMzN8IiRdFh9tLNRgd33EKWaibl7cS9N8T53kar6FKwyH0gitNnRiut0QkWsGTJAuLcAOYvqERVxfNYN6co0e5q3I209RQ6vQLGgQMYrikmgWFVh9cRQPM+9TjsLLi4b/6U+rWBykm57S74RRDujO+Vf8DG5MhPwiOhMEj3kRaZ/+BHdKlCJG+4Ua8fIG9IvvZ6siMLmh/+Nk5yE5/t9+E2rkF6lzKUMUALkeGNcMivswZ5uVka5js7OmFI82TFjYaomog0QaQrfPrNNvx3H/0H7kHPU/vhYNXHsYjJEAmOg10fUUjg+FEFNklzJb6bGKoEQIde26LCp33mc+h79in9rW/fHmR9/SEaH5sb1ScQJUY4yFiNVICfxZVFq65CIy3hyw9+kS2zv+CZZ56RdjgFb8KuXbswhX3HQ4cOaHgvYM6juYDkADLWkugJAhVHzGo6UgqT3pq4hLTJpDja6ZuCT3L4+ssx/8EV5P+DCUZHrGn/X99Bzg9+DBsjQ4zKj7AeKFZgIOvz0dzt8xcjwlRYCyN0bwvTZFtfv54vwl01sn4pITFEweUc/QTGtXfchj8/8ywe++3v9XtP/PEp3PfZuxl4bCgvL8P7O3YR2xxspOaz8s3yuicjPy5jJVICkwEE33CQ7W+7TmhdfdUaJmQWFBXmo/JIJa5edzV++fZ9+KTHO6VfQ5DFFsfcefDcTXIy2K844Vi4hKa/h8+LGSX64Fy2Ei1f+QI8n/0CnAuXKsVp/8/vImnlakaIAJKvuU4psfCHELHDMmkKoqwUSxNU1ruC1LuD5i2HxerAL3/2A6XpL7/8KrvcqaT72Whhu1+avNIbfERGSCQC2MniBOzSPcnwMyyWFE9VpVjJEWIMSX6aUnXvNfikxwMb+tXktenJ6CCFEGF7ZF+MeHFtkkRZ+QnStD1330esSNGoEWO7XoSVXTYluZU0iQVYmCL7+NsPGaUK2W5rIJaIz+fnZ+PNN9i2I1ZJJptEHlNTUy2cTBmgid2pENmugqEsTL6U8H8jHGRjEg3EZPwMgQGGtSRahNQLZcZvdfoD7B+69TdSNuvs7EJHZwdefGELXnn1Jfz2sd/zt4kQKuFUIoiNCtyw/hp0xDKQSnDliRCUnoB0e6iAGK8zzN9acvPgmD1Xq8IS8jSXZMjTLhHdw5yZrTgwevTLDAPZZLytXUfuUnm+Nr5ec+UazJkzG5WVR/V7EsoTikhS9O9mkVXG6GTY0uRwJD0SiYTG2lgumc4wG/RHUgQNEJHTSS0FH6RGIIONGczwamtrcfp0vWLHbx77Hf7+97/g+ef/oYvYunUr//YbnSKpPHoS+1lNWrRoIZr8QVQGY+jj7k0iH7cz0Rp8ZytcjNkY6fWJdYQaT3PnzbCyZiAKCBLpJRyGOztp7pNo6kOoC0bQSDIjYU1mmXbs2MHUneej0qtY2M1le3/79vc1VNfW1uCKZct07Ebqm14qtI3+L4+xvkAkaqQFmuhDNmqG7eVARPMDs9lOXAjQ/IMkD63c7V70C5DFDBRkCM+/8Ao7rkX41rcfQmHRZPz054/hyivXYsuWLWjv6KJlhbBo4SKdOpGZokxyAM/V1+INP8kMRa4iMgcJYhYueIgtbwu5R1xKYawBCuGJsBRuZE7Qw4x0F693JhxFE3vgXQTDFIZT2cUnn3xGBzorKvbohKhMkJaVlTPxyUzUK2jo27bv1JxmyOtDVxdNn9iQI/MGo1xe5oNCAZ/O2VHtmg9IWhzj58Ggn9rz6aCiIKjM5s2ZM5N7FuPJOrFyxTJ861vfwPZt7+KWTetZWHHj7a1vI43PSU4L7rnn00rSZaeq2Om5445/RX1LM6Jc0JMGB7YzBd/Z1ArzfzyMvYcr0ckq0OG2DvYnutFGt6tiWrvblYo6g1kjggw62FnxjdKVvOxqb9iwTueIHSyDn6qr06EpAbiS4kljuUozw+47/9wKH8OmYJ1dRuuIAxNqgoKUMnMrYVFOKCFQTF+0LB1i8fe//vV5xQapESxevBj3fObTWL78Cvzbv/0P1g7K8Je/vYhVK1fgwS8/iD/96SmNtydPnqBrpOLdd99lkWUxnnj89/RZ+i93ecrUYhwliIUozJ6jx3C0fxCDjP2NvF5NF9vmSS5dgwgtlF1CsvB+cdcuuoSMwA2zf1lZWal0XgjcaZKcdnaQJ0+eNAGEZczn0OEjik1ikRLaJypgBAxlylIA0cwCpihE8ED+1shFyDCijJzp4AQxYvv27XjnnXfx4Je+yNc7cMstm6mobrzKHoIkWitXrdJzimk2NjTpRQ8dPKTWIIoWq1u+fLnyD7mGKEoyNSuJjYzlyqyCzC3JhJeM8QQYBo1EcQ/zBRnO0nlF5i1yfhE8n/FdhqR27tipmGAwTCyKCiOUjQ1TLgHE83qDIZZ2YjHBArviQWdnD/8WodDMwVnUyGKJurGxRbUdpS9eu34DtX9cLeTQ4ePYs2c/Xn/zn3jy6ed0VH7Ly6/pwHJnVz/WrF2rAxcyP5zLBKWLRZZyLlLmhZ0ERalHCH93MtTFpJAlCqHQArpR4pOfEUmmu7q6enQmUHh/L3N7AzdLZhfcBHAZu29p7aA1G3WmeHpp6QT5WC1ATe1p1gbjlMl/fm8wHPbrLIBgwLB3UDGgu7uTSpBsMMoFeGh6DDtMTb38vLAgF+vXr8POnTvYUZ6O73/vW/ysC7ffthmn60/h4Ye+iddef51RYI7G39aWFlZimpRVimV4Gcpk8ruDiCyfy40X3//e9xEJh7RiM0gfl2JG0O8lPkmmOsTfGslSkxXF7fR7H4EtSCttOHNalRZnf0MGvfYx0ZrD8te59Yte1hr62feU3qcQoe9Go+FxU+NCOxOdF7lwgiIbND0Wa5Ldl/eCujLaLjvfQ7AqZuo5o7wc//cPf9R+kMTgG264XtNRmTF8hSxMOk3l/I6MvXvS2XpnWiwjti6XU88zRGWIdTzzYhWaBhfCkrYSeyqjqGpKwf4qEwYipahrT0dDdzaaevNwstGNRr6ubfXgUI0FPYFi/s2Ffn6vY2gSBqPliDkWoj80DWZHEUKDR8fSd7EYunjQTJVIMp19LhaIfwrAyLi8xcTYzN2S2WDxxV4ZSSUwsoyqz7JTRRR03759OhZ/1x2fwsPcRQGul15+g1lXCz7/+ft0crystJx9xiIcJtqvWXOl+qgMZ8n5G5ipCVCVLbwbH1TPw8m3ZDXJI6vagFNsK+49jXHLZZO0YXTVJeBPJx7cy+4hNn2nbUCghwWX5ufGPpLbbXjtPvYFzDX0jTEFjNb5o4zz/gApKjNFiyXGuuGQ+pXNIbe8GCl4gDF1mAtuw7SSyVpoEHyo37sfBymcDCPVnW7SmyhqSUN37PgADz30Xbzz7nbddelDyLRZaVkZqquqGZOziQWdOH78JMqKl+L4mTodzhDyJUAod5T09zZhVkkUn+TotBxD+zl9jUjMWGs2GWMV9I1Vo18cne2VUBMkGZJJzmFDUH1OcgGT2ap+NDycmCFs4q4NDXarFXyZoS8eX4hDB/bjuvVX4dZP3YLHSI2zszL1XoFa5uetzU0Me5UsuaVhxYrl+MUvfq0KbGXtcHppCXsQe3H99R4cxJ8xr3S+3qkioe/EiZM4XPE7PP3ZXnySY+cBYMfLmDC7bDJYd5vp268yzH3zQnmgnxkAAAWpSURBVGNvGhYZLkymuJaTpI4uk2TZWR41IekXCncQtjeZFFVKZ7KLi5csRk11NV588SW1imS3XVH+Rz/8CTbfcivmzp2NgvwCpaYCWsIv5JBEpr6+QeO+j7FdWnMS4hI8xIDiGZvx3ql0hrKT/H0+jhw5ovcbyC0yzSxxJbkSd48IOZMql5Ci1NR0WrARnd1BXqF5TDaj3s9kec3c2tq6Oy0trZq7WXohzanQviDN1a5xU6JqFxcsM7eyqFkEti4mQzJJLnzgxhs36ZDy9OnTmQccY5i8Dh+yGryDcVkAUSY1+xiqTtDUFy1eRGHNmETCIjFdyIkoWj4X8++gArKysnReuZe8v6t7GLUtM1HfPghvNBPv7QkTfDORNpRMvPEnhrAsDlptEqtAAzjTkK7j/zIN2d/vVSAPjTQxKXy1yK7on5qa4w1HIpvjRI1za37yPjEUYVQ+4EpOI4kIa9LU3zeouCCDybt27yMxStcbKILc2WrSUYkUb7z5tlZh5caIT7EOv/39D0hd16vgYt4NDc2JwQx+95QWLE2J6hSvJfcNGfX+hTi6u3r52x3sV85VTDh+olp3O41VJEF0YZaRSFxrmQMjN09JYcXrC2imKBxC5BNsk913OlL+w+vtP6wK4ItKtzvp+kg4mJ8AgvNnf8WHpZoaYiVHZu7lLo+OjjYlH0FiQye5QXnZNKacLprskN5bFCTXnjdvLhUYQcnUSYwe3Yzrw8wPbCRMezB1yuSREf2guojMJMudYrRetTDh78LaosxWRSkChBnMMHt7u4kZzYn7gsgXTFyXjMk7nXZN1Hq7O3XtkhnKuKzUPaUHIB0vIU92m+mjrq62L4tko/E/zlx5J5/voTJtFyt7C2rH4gZNl70kH4LQdkYFIUtCj4ULRPgdGUQWypnoxkbYk+vShbWQBBUVTdKFOKWcxYsJsfmI4bOgsAAHSZFdLMO10J+FwR0+fJju56d1ZKn77a6o0DRXdlQSIdl1SGRiYiRUWIBb7lsUniHnlrqGX3EmQedFeDLRIer8OuKK9vrGCBD/0EOkP8Tv3M4dM11IAaopKkBulJQIIGZsZVopvT+p6MidZUKP5b5BATAx8XyCnYS4LObzVub6UqJubWtRXm+jAqsYAt0kQnLILieRBjeS0cldZhkZGWR7HaxBZCg2SL/RbJF5/35aWLcmZSRyeheL4IcILYOdstt6D6FsRkCEH9bzMzELO92eWzrbW/aOyjPhvkEq4VRaZt5+CrOJv7VeqA8g7+XEggniU2bmC+KTUouTxYVCGmf4PbPegNHQ0KIAJrxBFFZICyhk/UBwxUoC1N07qN0nyQf62KP0klsYzRbFmxB3U+5jkkFu2Vkn3UsuLdUcKd9HeQ7pS0ilqre3X9/7WWcIBEUBPrVGAT2xDO68V4Rva67bOl7m8+4c9Q72nSI1fYl0dxF3uiA+Mn9/ofsBhJuLIFJLkHsNxLTlLhCfd0DpsPi+JDIGQ4xssF1n+CVx8RMjpOosOJLsdqtFyb2DspNSsenqaidPSE2QH5q2hzVKsQjxedlZL88vOGAjM5VQKjXNQVpFmN8RqxCfF1yR80ukos/voTzXjd/5MQPHxQ8DS1qfoRIfCgX908Z4wjn3/UmYMRoi6qNyi43E5VgkqDFZ0FYmMjyM0xGCqBQhCwokR48qwRJhprILLHdwiJ6FastkitzkJFRcOIbJZKXgwbG0XO76CocDWtgQjiIWaWWclxxfxJHrSSIngjPs1Vqtrkfb2xufAS58F/mlJ4hGvpObm7uKfOA6PpZyScWsVWXyAo7xCjGMjKGIyQpTFGUICDqdbs0wRQBpRkrKKwK73ImmrMPpUsuRXECsyUimKUVU4RUDBDsjXUyqVAJ4UqRJ3M43TMvoU4S3jFyPbujn+664wVJvNsb2cC1vMVv82Nvn/z8AAAD//95MeMAAAAAGSURBVAMAtNKZ5dqcdFkAAAAASUVORK5CYII='
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
    d.issues?.length ? jsx('div', { className: 'gr-chips', children: d.issues.slice(0, 4).map((i, n) => jsx('span', { className: 'gr-chip gr-issue', children: issueText(i) }, n)) }) : null,
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
    q.chart?.svg
      // Drawn by the plugin's own report code; every value in it is HTML-escaped there.
      ? jsx('div', { className: 'gr-svg', dangerouslySetInnerHTML: { __html: q.chart.svg } })
      : jsx(Bars, { q }),
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
.gr-svg svg{width:100%;max-width:640px;margin:10px 0;display:block}.gr-svg .bar,.gr-svg .cell{fill:var(--ui-accent)}
.gr-svg .pt{fill:var(--ui-accent);stroke:var(--background);stroke-width:2}.gr-svg .grid{stroke:var(--ui-stroke-secondary);stroke-width:1}
.gr-svg .lbl{fill:var(--ui-text-tertiary);font-size:11px}
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
