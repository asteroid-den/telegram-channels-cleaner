import { useMediaQuery } from '@vueuse/core'

/** A phone-sized screen: the same app, laid out for one column and a thumb (Tailwind's `max-md`). */
export const useNarrow = () => useMediaQuery('(max-width: 767px)')
