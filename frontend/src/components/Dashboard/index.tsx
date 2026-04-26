import { useEffect, useState } from 'react'
import { Sidebar, type NavId } from './Sidebar'
import { Main } from './Main'
import { RightRail } from './RightRail'
import { Analytics } from './Analytics'
import { GeoPanel } from './GeoPanel'
import { Campaigns } from './Campaigns'
import { Library } from './Library'
import { Pipeline } from './Pipeline'
import { Reports } from './Reports'
import { Settings } from './Settings'
import { VoicePane } from './VoicePane'
import { NavContext } from './navContext'
import { AudiencePane } from '../audience/AudiencePane'
import { useAssetLibraryStore } from '../../stores/assetLibraryStore'
import type { Brand } from './types'

export type { Brand, Competitor } from './types'

export function Dashboard({ brand }: { brand: Brand }) {
  const [view, setView] = useState<NavId>('dashboard')

  // Prime the asset library at the Dashboard level (not inside the Library
  // page) so brandId is known before the user kicks off any storyboard
  // run. This is what makes ``video.scene_generated`` etc. land as
  // optimistic prepends + scheduled refetches even when the user hasn't
  // visited the Library page yet during this session.
  const loadAssets = useAssetLibraryStore((s) => s.load)
  useEffect(() => {
    void loadAssets(brand.id)
  }, [brand.id, loadAssets])

  return (
    <NavContext.Provider value={{ navigate: setView }}>
      {(() => {
        if (view === 'audience') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <AudiencePane brandId={brand.id} brandName={brand.name} />
            </div>
          )
        }

        if (view === 'analytics') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <Analytics brand={brand} />
            </div>
          )
        }

        if (view === 'geo') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <GeoPanel brand={brand} />
            </div>
          )
        }

        if (view === 'campaigns') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <Campaigns brand={brand} />
            </div>
          )
        }

        if (view === 'library') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <Library brand={brand} />
            </div>
          )
        }

        if (view === 'pipeline') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <Pipeline brand={brand} />
            </div>
          )
        }

        if (view === 'reports') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <Reports brand={brand} />
            </div>
          )
        }

        if (view === 'settings') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <Settings brand={brand} />
            </div>
          )
        }

        if (view === 'voice') {
          return (
            <div className="grid min-h-screen grid-cols-[260px_1fr]">
              <Sidebar brand={brand} active={view} onNavigate={setView} />
              <VoicePane brand={brand} />
            </div>
          )
        }

        return (
          <div className="grid min-h-screen grid-cols-[260px_1fr_320px]">
            <Sidebar brand={brand} active={view} onNavigate={setView} />
            <Main brand={brand} />
            <RightRail brand={brand} />
          </div>
        )
      })()}
    </NavContext.Provider>
  )
}
