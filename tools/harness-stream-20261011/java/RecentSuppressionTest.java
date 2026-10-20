package xiaozhi.modules.personmemory;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class RecentSuppressionTest {
 @Test void causalBoundaryPreservesImmediateResave() {
  var change=new HashMap<String,Object>();change.put("match_text","*");change.put("material_cutoff_id",10L);change.put("archive_cutoff_id",20L);change.put("created_at",new Date(1000));
  var row=new HashMap<String,Object>();row.put("record_id","material:10");row.put("id",10L);row.put("created_at",new Date(1000));
  assertTrue(RecentArchiveService.suppressedBy(row,change,"喜欢咖啡"));
  row.put("id",11L);row.put("record_id","material:11");assertFalse(RecentArchiveService.suppressedBy(row,change,"喜欢咖啡"));
  row.put("record_id","archive:21");row.put("id",21L);assertFalse(RecentArchiveService.suppressedBy(row,change,"喜欢咖啡"));
  row.put("id",20L);assertTrue(RecentArchiveService.suppressedBy(row,change,"喜欢咖啡"));
 }
 @Test void unrelatedFactAndLegacyMarkerRemainCompatible() {
  var row=Map.<String,Object>of("record_id","material:1","id",1L,"created_at",new Date(1000));
  var change=Map.<String,Object>of("match_text","喜欢咖啡","created_at",new Date(1000));
  assertTrue(RecentArchiveService.suppressedBy(row,change,"喜欢咖啡"));
  assertFalse(RecentArchiveService.suppressedBy(row,change,"宠物叫豆豆"));
 }
}
