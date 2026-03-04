import { ref, onMounted } from 'vue'

const currentTheme = ref(localStorage.getItem('th-theme') || 'system')

/**
 * Applies the theme to the document root element.
 * For 'dark' → adds 'dark' class
 * For 'light' → removes 'dark' class
 * For 'system' → checks OS preference via matchMedia
 */
function applyTheme(theme) {
    const root = document.documentElement
    let isDark = false

    if (theme === 'dark') {
        isDark = true
    } else if (theme === 'light') {
        isDark = false
    } else {
        // system mode — check OS preference
        isDark = window.matchMedia('(prefers-color-scheme: dark)').matches
        console.log('[Theme] System mode — browser reports prefers-color-scheme dark:', isDark)
    }

    console.log('[Theme] Applying:', theme, '→ isDark:', isDark)

    if (isDark) {
        root.classList.add('dark')
    } else {
        root.classList.remove('dark')
    }
}

// Apply theme IMMEDIATELY when module is loaded (before any component mounts)
// This prevents the flash of wrong theme
applyTheme(currentTheme.value)

// Listen for OS theme changes in real-time (only matters when mode is 'system')
if (typeof window !== 'undefined') {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', (e) => {
        if (currentTheme.value === 'system') {
            applyTheme('system')
        }
    })
}

export function useTheme() {
    function setTheme(theme) {
        currentTheme.value = theme
        localStorage.setItem('th-theme', theme)
        applyTheme(theme)
    }

    // Re-apply on mount as a safety net (e.g. after hydration)
    onMounted(() => {
        applyTheme(currentTheme.value)
    })

    return {
        currentTheme,
        setTheme,
    }
}
