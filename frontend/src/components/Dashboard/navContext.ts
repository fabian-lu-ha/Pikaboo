import { createContext, useContext } from 'react'
import type { NavId } from './Sidebar'

// Lightweight nav bridge. Lets descendants like TopBar trigger view changes
// without having to be passed an ``onNavigate`` prop through every page that
// renders them. Sidebar still uses the explicit ``onNavigate`` prop because
// it's a direct child of Dashboard and carries the active state.
type NavContextValue = {
  navigate: (id: NavId) => void
}

export const NavContext = createContext<NavContextValue>({
  navigate: () => {},
})

export function useNav(): NavContextValue {
  return useContext(NavContext)
}
