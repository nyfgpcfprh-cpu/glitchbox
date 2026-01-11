' ProgressService (local registry, explicit)
function ProgressService_Load(itemId as String) as Object
    if itemId = invalid or itemId = "" then return invalid
    section = CreateObject("roRegistrySection", "GlitchBox")
    key = "progress_" + itemId
    if section.Exists(key) then
        raw = section.Read(key)
        parts = raw.Split("|")
        if parts.Count() >= 2 then
            return {
                position: val(parts[0]),
                duration: val(parts[1])
            }
        end if
    end if
    return invalid
end function

sub ProgressService_Save(itemId as String, position as Integer, duration as Integer)
    if itemId = invalid or itemId = "" then return
    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Write("progress_" + itemId, position.toStr() + "|" + duration.toStr())
    section.Flush()
end sub

sub ProgressService_Clear(itemId as String)
    if itemId = invalid or itemId = "" then return
    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Delete("progress_" + itemId)
    section.Flush()
end sub
