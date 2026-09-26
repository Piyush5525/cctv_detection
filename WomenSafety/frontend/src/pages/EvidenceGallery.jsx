import { useState, useEffect } from 'react'
import { Video, Download, Trash2, Play, X, Clock, HardDrive } from 'lucide-react'
import axios from 'axios'

export function EvidenceGallery() {
  const [clips, setClips] = useState([])
  const [loading, setLoading] = useState(true)
  const [playing, setPlaying] = useState(null)

  const load = async () => {
    try {
      const res = await axios.get('/api/v1/evidence')
      setClips(res.data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const del = async (filename) => {
    await axios.delete(`/api/v1/evidence/${filename}`)
    setClips(c => c.filter(x => x.filename !== filename))
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Evidence Gallery</h1>
          <p className="text-sm text-slate-500 mt-0.5">{clips.length} clips saved</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
        </div>
      ) : clips.length === 0 ? (
        <div className="card text-center py-20">
          <Video className="w-10 h-10 mx-auto mb-3 text-slate-700" />
          <p className="text-sm text-slate-500">No evidence clips yet</p>
          <p className="text-xs text-slate-600 mt-1">Clips are saved automatically when incidents are detected</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {clips.map(clip => (
            <ClipCard
              key={clip.filename}
              clip={clip}
              onPlay={() => setPlaying(clip)}
              onDelete={() => del(clip.filename)}
            />
          ))}
        </div>
      )}

      {/* Fullscreen player */}
      {playing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm"
          onClick={() => setPlaying(null)}>
          <div className="relative w-full max-w-3xl mx-4" onClick={e => e.stopPropagation()}>
            <div className="bg-[#0d1526] border border-[#1a2540] rounded-2xl overflow-hidden shadow-2xl">
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#1a2540]">
                <div>
                  <p className="text-sm font-semibold text-slate-200">{playing.filename}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {new Date(playing.created).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <a href={`/api/v1/evidence/${playing.filename}`} download
                    className="btn-ghost text-xs border border-[#1a2540]">
                    <Download className="w-3.5 h-3.5" /> Download
                  </a>
                  <button onClick={() => setPlaying(null)}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <video
                src={`/api/v1/evidence/${playing.filename}`}
                controls autoPlay
                className="w-full bg-black"
                style={{ maxHeight: '65vh' }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ClipCard({ clip, onPlay, onDelete }) {
  const sizeKb = (clip.size / 1024).toFixed(0)
  const name = clip.filename.replace('.mp4', '')
  const thumbFile = `${name}_thumb.jpg`

  return (
    <div className="card p-0 overflow-hidden group">
      {/* Thumbnail / preview */}
      <div className="relative bg-black" style={{ aspectRatio: '16/9' }}>
        <img
          src={`/api/v1/evidence/thumbnail/${thumbFile}`}
          alt="clip thumbnail"
          className="w-full h-full object-cover opacity-70"
          onError={e => { e.target.style.display = 'none' }}
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <button
            onClick={onPlay}
            className="w-12 h-12 rounded-full bg-black/60 border border-white/20 flex items-center justify-center
              hover:bg-emerald-500/30 hover:border-emerald-500/50 transition-all duration-150"
          >
            <Play className="w-5 h-5 text-white ml-0.5" />
          </button>
        </div>
      </div>

      {/* Info */}
      <div className="p-3">
        <p className="text-xs font-medium text-slate-300 truncate">{clip.filename}</p>
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-3 text-[10px] text-slate-600">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(clip.created).toLocaleDateString()}
            </span>
            <span className="flex items-center gap-1">
              <HardDrive className="w-3 h-3" />
              {sizeKb} KB
            </span>
          </div>
          <div className="flex items-center gap-1">
            <a href={`/api/v1/evidence/${clip.filename}`} download
              className="p-1.5 rounded-lg text-slate-600 hover:text-slate-400 hover:bg-white/5 transition-colors">
              <Download className="w-3.5 h-3.5" />
            </a>
            <button onClick={onDelete}
              className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-colors">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default EvidenceGallery
